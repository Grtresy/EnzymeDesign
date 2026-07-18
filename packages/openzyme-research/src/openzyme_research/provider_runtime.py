from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
import hashlib
import ipaddress
import json
import socket
import time
from typing import Any
from typing import Callable
from typing import Generic
from typing import Mapping
from typing import TypeVar
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.parse import urlunsplit
from urllib.request import Request
from urllib.request import urlopen


T = TypeVar("T")


class ProviderOutcome(StrEnum):
    COMPLETED = "completed"
    EMPTY = "empty"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    attempt: int
    started_at: str
    finished_at: str
    outcome: str
    status_code: int | None = None
    error_code: str | None = None
    retry_after_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    error_code: str
    message: str
    retryable: bool
    status_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProviderProvenance:
    provider: str
    operation: str
    endpoint_id: str
    request_digest: str
    retrieved_at: str
    attempt_count: int
    attempts: tuple[ProviderAttempt, ...]
    response_digest: str | None = None
    response_status: int | None = None
    request_ids: tuple[str, ...] = ()
    page_count: int | None = None
    release: str | None = None
    api_version: str | None = None
    truncated: bool = False
    cache_status: str = "disabled"
    safe_response_headers: tuple[tuple[str, str], ...] = ()
    provider_identity: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "operation": self.operation,
            "endpoint_id": self.endpoint_id,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "retrieved_at": self.retrieved_at,
            "response_status": self.response_status,
            "attempt_count": self.attempt_count,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "request_ids": list(self.request_ids),
            "page_count": self.page_count,
            "release": self.release,
            "api_version": self.api_version,
            "truncated": self.truncated,
            "cache_status": self.cache_status,
            "safe_response_headers": dict(self.safe_response_headers),
            "provider_identity": dict(self.provider_identity),
        }


@dataclass(frozen=True, slots=True)
class ProviderCallResult(Generic[T]):
    outcome: ProviderOutcome
    items: tuple[T, ...]
    provenance: ProviderProvenance
    failure: ProviderFailure | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.outcome is ProviderOutcome.COMPLETED and not self.items:
            raise ValueError("completed provider result requires at least one item")
        if self.outcome is ProviderOutcome.EMPTY and self.items:
            raise ValueError("empty provider result cannot contain items")
        if self.outcome in {ProviderOutcome.DEGRADED, ProviderOutcome.FAILED} and self.failure is None:
            raise ValueError("degraded/failed provider result requires a failure")
        if self.outcome in {ProviderOutcome.COMPLETED, ProviderOutcome.EMPTY} and self.failure is not None:
            raise ValueError("completed/empty provider results cannot carry a failure")

    @property
    def cutover_usable(self) -> bool:
        # A schema-valid empty response can be a healthy provider operation, but
        # it is never positive cutover evidence by itself. Requirement-specific
        # quorum policy decides whether the completed records are sufficient.
        return self.outcome is ProviderOutcome.COMPLETED

    def to_dict(self, *, item_serializer: Callable[[T], Any] | None = None) -> dict[str, Any]:
        serialize = item_serializer or _serialize_item
        return {
            "outcome": self.outcome.value,
            "items": [serialize(item) for item in self.items],
            "provenance": self.provenance.to_dict(),
            "failure": None if self.failure is None else self.failure.to_dict(),
            "warnings": list(self.warnings),
        }

    def to_summary_dict(self) -> dict[str, Any]:
        """Return the public-safe call envelope without provider item bodies."""

        return {
            "outcome": self.outcome.value,
            "item_count": len(self.items),
            "provenance": self.provenance.to_dict(),
            "failure": None if self.failure is None else self.failure.to_dict(),
            "warnings": list(self.warnings),
        }


class ProviderRequestError(RuntimeError):
    """A safe, typed provider failure that never embeds credentials or raw URLs."""

    def __init__(self, result: ProviderCallResult[Any]) -> None:
        if result.failure is None:
            raise ValueError("ProviderRequestError requires a failed provider result")
        self.result = result
        self.error_code = result.failure.error_code
        super().__init__(result.failure.message)


@dataclass(frozen=True, slots=True)
class ProviderHttpResponse:
    body: bytes
    provenance: ProviderProvenance

    def json_object(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise provider_schema_error(
                self.provenance,
                "provider response is not valid UTF-8 JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise provider_schema_error(
                self.provenance,
                "provider response JSON root must be an object",
            )
        return payload


OpenCallable = Callable[..., Any]
SleepCallable = Callable[[float], None]
NowCallable = Callable[[], datetime]


_SAFE_RESPONSE_HEADERS = {
    "content-type",
    "etag",
    "last-modified",
    "retry-after",
    "x-api-version",
    "x-request-id",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "x-uniprot-release",
}
_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


@dataclass(slots=True)
class BoundedHttpClient:
    opener: OpenCallable = urlopen
    sleeper: SleepCallable = time.sleep
    now: NowCallable = lambda: datetime.now(UTC)
    max_attempts: int = 3
    timeout_seconds: float = 30.0
    backoff_seconds: tuple[float, ...] = (0.5, 1.0)
    max_retry_after_seconds: float = 30.0

    def request(
        self,
        *,
        provider: str,
        operation: str,
        endpoint_id: str,
        url: str,
        request_identity: Mapping[str, Any],
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        empty_ok: bool = False,
        safe_provider_identity: Mapping[str, Any] | None = None,
    ) -> ProviderHttpResponse:
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        request_digest = _json_digest(
            {
                "provider": provider,
                "operation": operation,
                "endpoint_id": endpoint_id,
                "method": method.upper(),
                "request_identity": dict(request_identity),
                "body_digest": None if body is None else _content_digest(body),
            }
        )
        request = Request(
            url,
            headers={} if headers is None else dict(headers),
            method=method.upper(),
            data=body,
        )
        provider_identity = _safe_identity(safe_provider_identity or {})
        attempts: list[ProviderAttempt] = []
        for attempt_number in range(1, self.max_attempts + 1):
            started_at = self.now().astimezone(UTC).isoformat()
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                    raw = response.read()
                    status = int(getattr(response, "status", 200))
                    response_headers = _safe_headers(getattr(response, "headers", {}))
                    finished_at = self.now().astimezone(UTC).isoformat()
                    if not raw and not empty_ok:
                        attempts.append(
                            ProviderAttempt(
                                attempt=attempt_number,
                                started_at=started_at,
                                finished_at=finished_at,
                                outcome="failed",
                                status_code=status,
                                error_code="provider_schema_drift",
                            )
                        )
                        provenance = _provenance(
                            provider=provider,
                            operation=operation,
                            endpoint_id=endpoint_id,
                            request_digest=request_digest,
                            attempts=attempts,
                            response_status=status,
                            safe_response_headers=response_headers,
                            provider_identity=provider_identity,
                            retrieved_at=finished_at,
                        )
                        raise _failure_error(
                            provenance,
                            error_code="provider_schema_drift",
                            message=f"{provider} {endpoint_id} returned an empty required response",
                            retryable=False,
                            status_code=status,
                        )
                    attempts.append(
                        ProviderAttempt(
                            attempt=attempt_number,
                            started_at=started_at,
                            finished_at=finished_at,
                            outcome="completed",
                            status_code=status,
                        )
                    )
                    return ProviderHttpResponse(
                        body=raw,
                        provenance=_provenance(
                            provider=provider,
                            operation=operation,
                            endpoint_id=endpoint_id,
                            request_digest=request_digest,
                            attempts=attempts,
                            response_digest=_content_digest(raw),
                            response_status=status,
                            safe_response_headers=response_headers,
                            provider_identity=provider_identity,
                            retrieved_at=finished_at,
                        ),
                    )
            except ProviderRequestError:
                raise
            except HTTPError as exc:
                status = int(exc.code)
                retryable = status in _RETRYABLE_HTTP_STATUS
                error_code = _http_error_code(status)
                retry_after = _retry_after_seconds(
                    getattr(exc, "headers", {}),
                    now=self.now(),
                    cap=self.max_retry_after_seconds,
                )
                finished_at = self.now().astimezone(UTC).isoformat()
                will_retry = retryable and attempt_number < self.max_attempts
                attempts.append(
                    ProviderAttempt(
                        attempt=attempt_number,
                        started_at=started_at,
                        finished_at=finished_at,
                        outcome="retrying" if will_retry else "failed",
                        status_code=status,
                        error_code=error_code,
                        retry_after_seconds=retry_after if will_retry else None,
                    )
                )
                if will_retry:
                    self.sleeper(
                        retry_after
                        if retry_after is not None
                        else self._backoff(attempt_number)
                    )
                    continue
                provenance = _provenance(
                    provider=provider,
                    operation=operation,
                    endpoint_id=endpoint_id,
                    request_digest=request_digest,
                    attempts=attempts,
                    response_status=status,
                    safe_response_headers=_safe_headers(getattr(exc, "headers", {})),
                    provider_identity=provider_identity,
                    retrieved_at=finished_at,
                )
                raise _failure_error(
                    provenance,
                    error_code=error_code,
                    message=f"{provider} {endpoint_id} failed with HTTP status {status}",
                    retryable=retryable,
                    status_code=status,
                ) from exc
            except (TimeoutError, URLError, OSError) as exc:
                error_code = (
                    "provider_timeout"
                    if isinstance(exc, TimeoutError)
                    else "provider_unavailable"
                )
                finished_at = self.now().astimezone(UTC).isoformat()
                will_retry = attempt_number < self.max_attempts
                attempts.append(
                    ProviderAttempt(
                        attempt=attempt_number,
                        started_at=started_at,
                        finished_at=finished_at,
                        outcome="retrying" if will_retry else "failed",
                        error_code=error_code,
                    )
                )
                if will_retry:
                    self.sleeper(self._backoff(attempt_number))
                    continue
                provenance = _provenance(
                    provider=provider,
                    operation=operation,
                    endpoint_id=endpoint_id,
                    request_digest=request_digest,
                    attempts=attempts,
                    retrieved_at=finished_at,
                    provider_identity=provider_identity,
                )
                raise _failure_error(
                    provenance,
                    error_code=error_code,
                    message=(
                        f"{provider} {endpoint_id} failed after "
                        f"{attempt_number} bounded attempts"
                    ),
                    retryable=True,
                ) from exc
        raise AssertionError("unreachable")

    def _backoff(self, attempt_number: int) -> float:
        if not self.backoff_seconds:
            return 0.0
        index = min(attempt_number - 1, len(self.backoff_seconds) - 1)
        return max(0.0, float(self.backoff_seconds[index]))


@dataclass(slots=True)
class BoundedCallableClient:
    """Bound retries for provider SDK callables without exposing SDK exceptions.

    The provider SDK remains responsible for enforcing its per-call timeout. This
    seam bounds the number of SDK calls and normalizes the same attempt/provenance
    taxonomy used by :class:`BoundedHttpClient`.
    """

    sleeper: SleepCallable = time.sleep
    now: NowCallable = lambda: datetime.now(UTC)
    max_attempts: int = 3
    backoff_seconds: tuple[float, ...] = (0.5, 1.0)
    max_retry_after_seconds: float = 30.0

    def invoke(
        self,
        *,
        provider: str,
        operation: str,
        endpoint_id: str,
        request_identity: Mapping[str, Any],
        call: Callable[[], Mapping[str, Any]],
        safe_provider_identity: Mapping[str, Any] | None = None,
    ) -> ProviderHttpResponse:
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        request_digest = _json_digest(
            {
                "provider": provider,
                "operation": operation,
                "endpoint_id": endpoint_id,
                "request_identity": dict(request_identity),
            }
        )
        provider_identity = _safe_identity(safe_provider_identity or {})
        attempts: list[ProviderAttempt] = []
        for attempt_number in range(1, self.max_attempts + 1):
            started_at = self.now().astimezone(UTC).isoformat()
            try:
                payload = call()
                if not isinstance(payload, Mapping):
                    finished_at = self.now().astimezone(UTC).isoformat()
                    attempts.append(
                        ProviderAttempt(
                            attempt=attempt_number,
                            started_at=started_at,
                            finished_at=finished_at,
                            outcome="failed",
                            error_code="provider_schema_drift",
                        )
                    )
                    raise _failure_error(
                        _provenance(
                            provider=provider,
                            operation=operation,
                            endpoint_id=endpoint_id,
                            request_digest=request_digest,
                            attempts=attempts,
                            retrieved_at=finished_at,
                            provider_identity=provider_identity,
                        ),
                        error_code="provider_schema_drift",
                        message=f"{provider} {endpoint_id} returned a non-object response",
                        retryable=False,
                    )
                try:
                    raw = json.dumps(
                        dict(payload),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                except (TypeError, ValueError) as exc:
                    finished_at = self.now().astimezone(UTC).isoformat()
                    attempts.append(
                        ProviderAttempt(
                            attempt=attempt_number,
                            started_at=started_at,
                            finished_at=finished_at,
                            outcome="failed",
                            error_code="provider_schema_drift",
                        )
                    )
                    raise _failure_error(
                        _provenance(
                            provider=provider,
                            operation=operation,
                            endpoint_id=endpoint_id,
                            request_digest=request_digest,
                            attempts=attempts,
                            retrieved_at=finished_at,
                            provider_identity=provider_identity,
                        ),
                        error_code="provider_schema_drift",
                        message=f"{provider} {endpoint_id} returned a non-JSON response",
                        retryable=False,
                    ) from exc
                finished_at = self.now().astimezone(UTC).isoformat()
                attempts.append(
                    ProviderAttempt(
                        attempt=attempt_number,
                        started_at=started_at,
                        finished_at=finished_at,
                        outcome="completed",
                    )
                )
                return ProviderHttpResponse(
                    body=raw,
                    provenance=_provenance(
                        provider=provider,
                        operation=operation,
                        endpoint_id=endpoint_id,
                        request_digest=request_digest,
                        attempts=attempts,
                        response_digest=_content_digest(raw),
                        retrieved_at=finished_at,
                        provider_identity=provider_identity,
                    ),
                )
            except ProviderRequestError:
                raise
            except HTTPError as exc:
                status = int(exc.code)
                retryable = status in _RETRYABLE_HTTP_STATUS
                error_code = _http_error_code(status)
                retry_after = _retry_after_seconds(
                    getattr(exc, "headers", {}),
                    now=self.now(),
                    cap=self.max_retry_after_seconds,
                )
                finished_at = self.now().astimezone(UTC).isoformat()
                will_retry = retryable and attempt_number < self.max_attempts
                attempts.append(
                    ProviderAttempt(
                        attempt=attempt_number,
                        started_at=started_at,
                        finished_at=finished_at,
                        outcome="retrying" if will_retry else "failed",
                        status_code=status,
                        error_code=error_code,
                        retry_after_seconds=retry_after if will_retry else None,
                    )
                )
                if will_retry:
                    self.sleeper(
                        retry_after
                        if retry_after is not None
                        else self._backoff(attempt_number)
                    )
                    continue
                raise _failure_error(
                    _provenance(
                        provider=provider,
                        operation=operation,
                        endpoint_id=endpoint_id,
                        request_digest=request_digest,
                        attempts=attempts,
                        retrieved_at=finished_at,
                        response_status=status,
                        safe_response_headers=_safe_headers(
                            getattr(exc, "headers", {})
                        ),
                        provider_identity=provider_identity,
                    ),
                    error_code=error_code,
                    message=f"{provider} {endpoint_id} failed with HTTP status {status}",
                    retryable=retryable,
                    status_code=status,
                ) from exc
            except (TimeoutError, URLError, OSError) as exc:
                error_code = (
                    "provider_timeout"
                    if isinstance(exc, TimeoutError)
                    else "provider_unavailable"
                )
                finished_at = self.now().astimezone(UTC).isoformat()
                will_retry = attempt_number < self.max_attempts
                attempts.append(
                    ProviderAttempt(
                        attempt=attempt_number,
                        started_at=started_at,
                        finished_at=finished_at,
                        outcome="retrying" if will_retry else "failed",
                        error_code=error_code,
                    )
                )
                if will_retry:
                    self.sleeper(self._backoff(attempt_number))
                    continue
                raise _failure_error(
                    _provenance(
                        provider=provider,
                        operation=operation,
                        endpoint_id=endpoint_id,
                        request_digest=request_digest,
                        attempts=attempts,
                        retrieved_at=finished_at,
                        provider_identity=provider_identity,
                    ),
                    error_code=error_code,
                    message=(
                        f"{provider} {endpoint_id} failed after "
                        f"{attempt_number} bounded attempts"
                    ),
                    retryable=True,
                ) from exc
            except Exception as exc:
                sdk_error = _classify_provider_sdk_exception(exc)
                if sdk_error is not None:
                    status, error_code, retryable, response_headers = sdk_error
                    retry_after = _retry_after_seconds(
                        response_headers,
                        now=self.now(),
                        cap=self.max_retry_after_seconds,
                    )
                    finished_at = self.now().astimezone(UTC).isoformat()
                    will_retry = retryable and attempt_number < self.max_attempts
                    attempts.append(
                        ProviderAttempt(
                            attempt=attempt_number,
                            started_at=started_at,
                            finished_at=finished_at,
                            outcome="retrying" if will_retry else "failed",
                            status_code=status,
                            error_code=error_code,
                            retry_after_seconds=(
                                retry_after if will_retry else None
                            ),
                        )
                    )
                    if will_retry:
                        self.sleeper(
                            retry_after
                            if retry_after is not None
                            else self._backoff(attempt_number)
                        )
                        continue
                    raise _failure_error(
                        _provenance(
                            provider=provider,
                            operation=operation,
                            endpoint_id=endpoint_id,
                            request_digest=request_digest,
                            attempts=attempts,
                            retrieved_at=finished_at,
                            response_status=status,
                            safe_response_headers=_safe_headers(
                                response_headers
                            ),
                            provider_identity=provider_identity,
                        ),
                        error_code=error_code,
                        message=(
                            f"{provider} {endpoint_id} failed after "
                            f"{attempt_number} bounded attempts"
                            if status is None
                            else (
                                f"{provider} {endpoint_id} failed with provider "
                                f"status {status}"
                            )
                        ),
                        retryable=retryable,
                        status_code=status,
                    ) from exc
                finished_at = self.now().astimezone(UTC).isoformat()
                attempts.append(
                    ProviderAttempt(
                        attempt=attempt_number,
                        started_at=started_at,
                        finished_at=finished_at,
                        outcome="failed",
                        error_code="provider_unavailable",
                    )
                )
                raise _failure_error(
                    _provenance(
                        provider=provider,
                        operation=operation,
                        endpoint_id=endpoint_id,
                        request_digest=request_digest,
                        attempts=attempts,
                        retrieved_at=finished_at,
                        provider_identity=provider_identity,
                    ),
                    error_code="provider_unavailable",
                    message=f"{provider} {endpoint_id} is unavailable",
                    retryable=False,
                ) from exc
        raise AssertionError("unreachable")

    def _backoff(self, attempt_number: int) -> float:
        if not self.backoff_seconds:
            return 0.0
        index = min(attempt_number - 1, len(self.backoff_seconds) - 1)
        return max(0.0, float(self.backoff_seconds[index]))


def completed_result(
    items: tuple[T, ...],
    *,
    provenance: ProviderProvenance,
    warnings: tuple[str, ...] = (),
) -> ProviderCallResult[T]:
    return ProviderCallResult(
        outcome=ProviderOutcome.COMPLETED if items else ProviderOutcome.EMPTY,
        items=items,
        provenance=provenance,
        warnings=warnings,
    )


def degraded_result(
    *,
    provenance: ProviderProvenance,
    error_code: str,
    message: str,
    retryable: bool,
    status_code: int | None = None,
    items: tuple[T, ...] = (),
    warnings: tuple[str, ...] = (),
) -> ProviderCallResult[T]:
    return ProviderCallResult(
        outcome=ProviderOutcome.DEGRADED,
        items=items,
        provenance=provenance,
        failure=ProviderFailure(
            error_code=error_code,
            message=message,
            retryable=retryable,
            status_code=status_code,
        ),
        warnings=warnings,
    )


def failed_result(
    *,
    provenance: ProviderProvenance,
    error_code: str,
    message: str,
    retryable: bool,
    status_code: int | None = None,
) -> ProviderCallResult[Any]:
    return ProviderCallResult(
        outcome=ProviderOutcome.FAILED,
        items=(),
        provenance=provenance,
        failure=ProviderFailure(
            error_code=error_code,
            message=message,
            retryable=retryable,
            status_code=status_code,
        ),
    )


def _classify_provider_sdk_exception(
    exc: Exception,
) -> tuple[int | None, str, bool, Mapping[str, Any]] | None:
    """Classify common provider-SDK HTTP exceptions without importing the SDK.

    Tavily 0.7.x converts HTTP responses to its own exception classes and drops
    the urllib ``HTTPError`` shape used by the low-level client. Keep the shared
    runtime optional-dependency free while recognizing that stable public shape.
    Response-bearing httpx/requests exceptions are handled through their
    ``response.status_code`` and ``response.headers`` attributes.
    """

    response = getattr(exc, "response", None)
    status_value = getattr(response, "status_code", None)
    headers_value = getattr(response, "headers", {})
    status_by_name = {
        "UsageLimitExceededError": 429,
        "ForbiddenError": 403,
        "InvalidAPIKeyError": 401,
        "MissingAPIKeyError": 401,
        "BadRequestError": 400,
    }
    if status_value is None and exc.__class__.__name__ == "TimeoutError":
        return None, "provider_timeout", True, {}
    if status_value is None:
        status_value = status_by_name.get(exc.__class__.__name__)
    try:
        status = int(status_value)
    except (TypeError, ValueError):
        return None
    headers = headers_value if isinstance(headers_value, Mapping) else {}
    return (
        status,
        _http_error_code(status),
        status in _RETRYABLE_HTTP_STATUS,
        headers,
    )


def _parsed_ip_address(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        pass
    # libc accepts historical IPv4 spellings such as 127.1, 0177.0.0.1 and
    # 0x7f.0.0.1. Browsers/resolvers normalize them to private addresses, so the
    # policy must classify the same spellings instead of treating them as DNS.
    try:
        packed = socket.inet_aton(hostname)
    except OSError:
        return None
    return ipaddress.ip_address(packed)


def safe_public_locator(value: str) -> str | None:
    """Return a query-free public HTTP locator or ``None`` for private URLs."""

    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    hostname = parsed.hostname.casefold().rstrip(".")
    address = _parsed_ip_address(hostname)
    if (
        hostname in {"localhost", "localhost.localdomain"}
        or hostname.endswith(
            (
                ".localhost",
                ".local",
                ".internal",
                ".corp",
                ".lan",
                ".home.arpa",
                ".cluster",
                ".svc",
                ".consul",
                ".test",
                ".invalid",
                ".example",
            )
        )
        or (address is None and "." not in hostname)
    ):
        return None
    if address is not None:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            return None
    if hostname.endswith((".nip.io", ".sslip.io", ".xip.io")):
        # Public wildcard-DNS services can encode a link-local/private address
        # in an otherwise public-looking hostname. They are not valid evidence
        # locators for the fail-closed provider boundary.
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    host_part = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host_part
    if port is not None:
        netloc = f"{host_part}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", "", ""))


def provider_identity_digest(
    *,
    provider: str,
    identity: Mapping[str, Any],
) -> str:
    """Return an opaque stable identity binding without exposing raw values."""

    return _json_digest(
        {
            "provider": provider,
            "identity": {
                str(key): str(value)
                for key, value in sorted(identity.items(), key=lambda item: str(item[0]))
            },
        }
    )


def combine_provenance(
    provenances: tuple[ProviderProvenance, ...],
    *,
    operation: str,
    endpoint_id: str,
) -> ProviderProvenance:
    if not provenances:
        raise ValueError("combine_provenance requires at least one provenance record")
    provider = provenances[0].provider
    if any(item.provider != provider for item in provenances):
        raise ValueError("combined provenance must come from one provider")
    attempts = tuple(
        ProviderAttempt(
            attempt=index,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            outcome=attempt.outcome,
            status_code=attempt.status_code,
            error_code=attempt.error_code,
            retry_after_seconds=attempt.retry_after_seconds,
        )
        for index, attempt in enumerate(
            (
                attempt
                for provenance in provenances
                for attempt in provenance.attempts
            ),
            start=1,
        )
    )
    response_digests = [
        item.response_digest
        for item in provenances
        if item.response_digest is not None
    ]
    request_ids = tuple(
        dict.fromkeys(
            request_id
            for provenance in provenances
            for request_id in provenance.request_ids
        )
    )
    safe_headers = tuple(
        sorted(
            {
                key: value
                for provenance in provenances
                for key, value in provenance.safe_response_headers
            }.items()
        )
    )
    provider_identity = tuple(
        sorted(
            {
                key: value
                for provenance in provenances
                for key, value in provenance.provider_identity
            }.items()
        )
    )
    last = provenances[-1]
    return ProviderProvenance(
        provider=provider,
        operation=operation,
        endpoint_id=endpoint_id,
        request_digest=_json_digest(
            {"request_digests": [item.request_digest for item in provenances]}
        ),
        response_digest=(
            None
            if not response_digests
            else _json_digest({"response_digests": response_digests})
        ),
        retrieved_at=last.retrieved_at,
        response_status=last.response_status,
        attempt_count=len(attempts),
        attempts=attempts,
        request_ids=request_ids,
        page_count=sum(item.page_count or 1 for item in provenances),
        release=next(
            (item.release for item in reversed(provenances) if item.release),
            None,
        ),
        api_version=next(
            (item.api_version for item in reversed(provenances) if item.api_version),
            None,
        ),
        truncated=any(item.truncated for item in provenances),
        cache_status=(
            "disabled"
            if all(item.cache_status == "disabled" for item in provenances)
            else "mixed"
        ),
        safe_response_headers=safe_headers,
        provider_identity=provider_identity,
    )


def _provenance(
    *,
    provider: str,
    operation: str,
    endpoint_id: str,
    request_digest: str,
    attempts: list[ProviderAttempt],
    retrieved_at: str,
    response_digest: str | None = None,
    response_status: int | None = None,
    safe_response_headers: tuple[tuple[str, str], ...] = (),
    provider_identity: tuple[tuple[str, str], ...] = (),
) -> ProviderProvenance:
    headers = dict(safe_response_headers)
    request_id = headers.get("x-request-id")
    return ProviderProvenance(
        provider=provider,
        operation=operation,
        endpoint_id=endpoint_id,
        request_digest=request_digest,
        response_digest=response_digest,
        retrieved_at=retrieved_at,
        response_status=response_status,
        attempt_count=len(attempts),
        attempts=tuple(attempts),
        request_ids=() if request_id is None else (request_id,),
        release=headers.get("x-uniprot-release"),
        api_version=headers.get("x-api-version"),
        safe_response_headers=safe_response_headers,
        provider_identity=provider_identity,
    )


def _failure_error(
    provenance: ProviderProvenance,
    *,
    error_code: str,
    message: str,
    retryable: bool,
    status_code: int | None = None,
) -> ProviderRequestError:
    return ProviderRequestError(
        ProviderCallResult(
            outcome=ProviderOutcome.FAILED,
            items=(),
            provenance=provenance,
            failure=ProviderFailure(
                error_code=error_code,
                message=message,
                retryable=retryable,
                status_code=status_code,
            ),
        )
    )


def provider_schema_error(
    provenance: ProviderProvenance,
    message: str,
) -> ProviderRequestError:
    return _failure_error(
        provenance,
        error_code="provider_schema_drift",
        message=f"{provenance.provider} {provenance.endpoint_id}: {message}",
        retryable=False,
        status_code=provenance.response_status,
    )


def _http_error_code(status: int) -> str:
    if status == 429:
        return "provider_rate_limited"
    if status in {401, 403}:
        return "provider_auth_failed"
    if status in {400, 404, 405, 409, 422}:
        return "provider_invalid_request"
    return "provider_unavailable"


def _retry_after_seconds(
    headers: Mapping[str, Any],
    *,
    now: datetime,
    cap: float,
) -> float | None:
    raw = _header_value(headers, "Retry-After")
    if raw is None:
        return None
    value = raw.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        seconds = (target.astimezone(UTC) - now.astimezone(UTC)).total_seconds()
    return min(max(0.0, seconds), max(0.0, cap))


def _safe_headers(headers: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    safe: dict[str, str] = {}
    for key, value in headers.items():
        normalized = str(key).lower()
        if normalized in _SAFE_RESPONSE_HEADERS:
            safe[normalized] = str(value)
    return tuple(sorted(safe.items()))


def _header_value(headers: Mapping[str, Any], key: str) -> str | None:
    target = key.casefold()
    for header_name, value in headers.items():
        if str(header_name).casefold() == target:
            return str(value)
    return None


def _safe_identity(identity: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    safe: dict[str, str] = {}
    for key, value in identity.items():
        normalized = str(key).strip().casefold()
        if normalized in {
            "api_key",
            "authorization",
            "cookie",
            "email",
            "password",
            "secret",
            "token",
            "x-api-key",
        }:
            continue
        safe[normalized] = str(value)
    return tuple(sorted(safe.items()))


def _content_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _json_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _content_digest(encoded)


def _serialize_item(item: Any) -> Any:
    to_dict = getattr(item, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return item


__all__ = [
    "BoundedCallableClient",
    "BoundedHttpClient",
    "ProviderAttempt",
    "ProviderCallResult",
    "ProviderFailure",
    "ProviderHttpResponse",
    "ProviderOutcome",
    "ProviderProvenance",
    "ProviderRequestError",
    "combine_provenance",
    "completed_result",
    "degraded_result",
    "failed_result",
    "provider_identity_digest",
    "provider_schema_error",
    "safe_public_locator",
]
