from __future__ import annotations

from datetime import UTC
from datetime import datetime
from io import BytesIO
from urllib.error import HTTPError
from urllib.error import URLError

import pytest

from openzyme_research.provider_runtime import BoundedCallableClient
from openzyme_research.provider_runtime import BoundedHttpClient
from openzyme_research.provider_runtime import ProviderOutcome
from openzyme_research.provider_runtime import ProviderRequestError
from openzyme_research.provider_runtime import completed_result
from openzyme_research.provider_runtime import provider_identity_digest
from openzyme_research.provider_runtime import safe_public_locator


class UsageLimitExceededError(RuntimeError):
    """Provider-SDK-shaped exception used without installing a concrete adapter SDK."""


TavilyTimeoutError = type("TimeoutError", (RuntimeError,), {})


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = body
        self.status = status
        self.headers = headers or {}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _client(opener, *, sleeps: list[float] | None = None) -> BoundedHttpClient:
    recorded_sleeps = [] if sleeps is None else sleeps
    return BoundedHttpClient(
        opener=opener,
        sleeper=recorded_sleeps.append,
        now=lambda: datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        max_attempts=3,
        timeout_seconds=2,
    )


def _request(client: BoundedHttpClient):
    return client.request(
        provider="pubmed",
        operation="literature.search",
        endpoint_id="pubmed.esearch:v1",
        url="https://example.invalid/search?api_key=super-secret",
        request_identity={"query": "alternative oxidase", "limit": 5},
    )


def test_bounded_http_client_records_response_identity_without_url_or_secret() -> None:
    client = _client(
        lambda request, timeout: _Response(
            b'{"ok":true}',
            headers={
                "Content-Type": "application/json",
                "X-Request-Id": "req-1",
                "Authorization": "secret",
            },
        )
    )

    response = _request(client)

    assert response.json_object() == {"ok": True}
    provenance = response.provenance.to_dict()
    assert provenance["attempt_count"] == 1
    assert provenance["request_ids"] == ["req-1"]
    assert provenance["safe_response_headers"] == {
        "content-type": "application/json",
        "x-request-id": "req-1",
    }
    assert "super-secret" not in str(provenance)
    assert "example.invalid" not in str(provenance)


def test_429_retry_after_is_bounded_and_all_attempts_are_recorded() -> None:
    calls = 0
    sleeps: list[float] = []

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(
                request.full_url,
                429,
                "rate limited",
                {"Retry-After": "120", "X-RateLimit-Remaining": "0"},
                BytesIO(),
            )
        return _Response(b'{"ok":true}')

    response = _request(_client(opener, sleeps=sleeps))

    assert sleeps == [30.0]
    assert response.provenance.attempt_count == 2
    assert response.provenance.attempts[0].error_code == "provider_rate_limited"
    assert response.provenance.attempts[0].retry_after_seconds == 30.0
    assert response.provenance.attempts[1].outcome == "completed"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_non_retryable_http_status_fails_once(status: int) -> None:
    calls = 0
    sleeps: list[float] = []

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        raise HTTPError(request.full_url, status, "failed", {}, BytesIO())

    with pytest.raises(ProviderRequestError) as error:
        _request(_client(opener, sleeps=sleeps))

    assert calls == 1
    assert sleeps == []
    assert error.value.result.provenance.attempt_count == 1
    expected = "provider_auth_failed" if status in {401, 403} else "provider_invalid_request"
    assert error.value.error_code == expected
    assert "super-secret" not in str(error.value)


def test_transient_transport_failure_exhaustion_is_typed() -> None:
    sleeps: list[float] = []

    def opener(request, timeout):
        raise URLError("network unavailable")

    with pytest.raises(ProviderRequestError) as error:
        _request(_client(opener, sleeps=sleeps))

    assert error.value.error_code == "provider_unavailable"
    assert error.value.result.provenance.attempt_count == 3
    assert sleeps == [0.5, 1.0]
    assert "network unavailable" not in str(error.value)


def test_invalid_json_is_non_retryable_schema_drift() -> None:
    response = _request(_client(lambda request, timeout: _Response(b"not-json")))

    with pytest.raises(ProviderRequestError) as error:
        response.json_object()

    assert error.value.error_code == "provider_schema_drift"
    assert error.value.result.provenance.attempt_count == 1


def test_empty_and_completed_outcomes_are_distinct() -> None:
    response = _request(_client(lambda request, timeout: _Response(b"{}")))

    empty = completed_result((), provenance=response.provenance)
    completed = completed_result(({"pmid": "1"},), provenance=response.provenance)

    assert empty.outcome is ProviderOutcome.EMPTY
    assert completed.outcome is ProviderOutcome.COMPLETED
    assert empty.cutover_usable is False
    assert completed.cutover_usable is True
    assert completed.to_dict()["items"] == [{"pmid": "1"}]


def test_bounded_callable_records_retry_without_sdk_exception_text() -> None:
    calls = 0
    sleeps: list[float] = []

    def call():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(
                "https://private.invalid/?api_key=secret",
                503,
                "contains secret",
                {"Retry-After": "0"},
                BytesIO(),
            )
        return {"results": []}

    response = BoundedCallableClient(
        sleeper=sleeps.append,
        now=lambda: datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        max_attempts=2,
    ).invoke(
        provider="tavily",
        operation="literature.enrich",
        endpoint_id="tavily.search:v1",
        request_identity={"query": "AOX"},
        call=call,
    )

    assert calls == 2
    assert sleeps == [0.0]
    assert response.provenance.attempt_count == 2
    assert "secret" not in str(response.provenance.to_dict())
    assert "private.invalid" not in str(response.provenance.to_dict())


def test_tavily_usage_limit_exception_is_retried_as_safe_429() -> None:
    calls = 0
    sleeps: list[float] = []

    def call():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise UsageLimitExceededError(
                "quota exhausted for secret-ncbi@example.org token=tavily-secret"
            )
        return {"results": []}

    response = BoundedCallableClient(
        sleeper=sleeps.append,
        now=lambda: datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        max_attempts=2,
    ).invoke(
        provider="tavily",
        operation="literature.enrich",
        endpoint_id="tavily.search:v1",
        request_identity={"query": "AOX"},
        call=call,
    )

    assert calls == 2
    assert sleeps == [0.5]
    assert response.provenance.attempt_count == 2
    first_attempt = response.provenance.attempts[0]
    assert first_attempt.outcome == "retrying"
    assert first_attempt.status_code == 429
    assert first_attempt.error_code == "provider_rate_limited"
    serialized = str(response.provenance.to_dict())
    assert "secret-ncbi@example.org" not in serialized
    assert "tavily-secret" not in serialized


def test_tavily_sdk_timeout_uses_bounded_timeout_retry_taxonomy() -> None:
    calls = 0

    def call():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TavilyTimeoutError(3.0)
        return {"results": []}

    response = BoundedCallableClient(
        sleeper=lambda delay: None,
        now=lambda: datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        max_attempts=2,
    ).invoke(
        provider="tavily",
        operation="literature.enrich",
        endpoint_id="tavily.search:v1",
        request_identity={"query": "AOX"},
        call=call,
    )

    assert calls == 2
    assert response.provenance.attempts[0].error_code == "provider_timeout"
    assert response.provenance.attempts[0].status_code is None


@pytest.mark.parametrize(
    "locator",
    (
        "http://127.0.0.1/private",
        "http://127.1/private",
        "http://127.0.1/private",
        "http://0177.0.0.1/private",
        "http://0x7f.0.0.1/private",
        "http://169.254.1/private",
        "http://169.254.169.254/private",
        "https://169.254.169.254.nip.io/private",
        "https://127.0.0.1.sslip.io/private",
        "https://10.0.0.1.xip.io/private",
        "http://localhost/private",
        "https://user:password@example.org/private",
        "file:///tmp/private",
        "https://service.internal/private",
        "https://service.corp/private",
        "https://router.lan/private",
        "https://nas.home.arpa/private",
        "https://api.cluster/private",
        "https://service.namespace.svc/private",
        "https://vault.consul/private",
        "https://host.test/private",
        "https://host.invalid/private",
        "https://host.example/private",
    ),
)
def test_private_locators_are_rejected(locator: str) -> None:
    assert safe_public_locator(locator) is None


def test_public_locator_drops_query_and_fragment() -> None:
    assert (
        safe_public_locator("https://example.org/paper?id=1&token=secret#abstract")
        == "https://example.org/paper"
    )


def test_public_ipv6_locator_preserves_brackets_and_port() -> None:
    assert (
        safe_public_locator("https://[2606:4700:4700::1111]:8443/paper?q=secret")
        == "https://[2606:4700:4700::1111]:8443/paper"
    )


def test_provider_identity_digest_is_stable_distinct_and_opaque() -> None:
    first_identity = {
        "tool": "openzyme",
        "email": "ncbi-a@example.org",
        "api_key": "ncbi-key-a",
    }
    same_identity_reordered = {
        "email": "ncbi-a@example.org",
        "api_key": "ncbi-key-a",
        "tool": "openzyme",
    }
    second_identity = {
        "tool": "openzyme",
        "email": "ncbi-b@example.org",
        "api_key": "ncbi-key-a",
    }
    rotated_key_identity = {
        "tool": "openzyme",
        "email": "ncbi-a@example.org",
        "api_key": "ncbi-key-b",
    }

    first = provider_identity_digest(provider="ncbi", identity=first_identity)
    repeated = provider_identity_digest(
        provider="ncbi",
        identity=same_identity_reordered,
    )
    second = provider_identity_digest(provider="ncbi", identity=second_identity)
    rotated_key = provider_identity_digest(
        provider="ncbi",
        identity=rotated_key_identity,
    )

    assert first == repeated
    assert first != second
    assert first != rotated_key
    assert first.startswith("sha256:")
    assert len(first) == 71
    assert "ncbi-a@example.org" not in first
    assert "ncbi-b@example.org" not in second
    assert "ncbi-key-a" not in first
    assert "ncbi-key-b" not in rotated_key
