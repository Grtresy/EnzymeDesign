from __future__ import annotations

import json
import threading
import time
import urllib.error
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from typing import Callable

from .limits import LimiterRegistry
from .llm_debug import current_llm_debug_context
from .llm_debug import get_llm_debug_recorder
from .llm_debug import serialize_llm_payload
from .live_testing import LiveStageTimeout


ProviderCall = Callable[[], Any]
SleepFn = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class LlmProviderErrorClassification:
    category: str
    retryable: bool
    reason: str
    status_code: int | None = None
    retry_after_seconds: float | None = None
    error_type: str | None = None
    error_code: str | None = None
    error_param: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "retryable": self.retryable,
            "reason": self.reason,
            "status_code": self.status_code,
            "retry_after_seconds": self.retry_after_seconds,
            "error_type": self.error_type,
            "error_code": self.error_code,
            "error_param": self.error_param,
        }


class LlmProviderInvocationError(RuntimeError):
    """Raised when a provider invocation fails after runtime classification."""

    def __init__(
        self,
        message: str,
        *,
        classification: LlmProviderErrorClassification,
        original: BaseException,
    ) -> None:
        super().__init__(message)
        self.classification = classification
        self.original = original


def classify_llm_provider_error(exc: BaseException) -> LlmProviderErrorClassification:
    for item in _exception_chain(exc):
        if isinstance(item, LlmProviderInvocationError):
            return item.classification
        classification = _classify_single_error(item)
        if classification.category != "unknown_provider_error":
            return classification
    return LlmProviderErrorClassification(
        category="unknown_provider_error",
        retryable=False,
        reason="unknown_provider_error",
    )


def is_retryable_llm_provider_error(exc: BaseException) -> bool:
    return classify_llm_provider_error(exc).retryable


def max_attempts_from_retries(max_retries: int) -> int:
    """Convert a retry budget into the runtime's total-attempt budget."""
    retries = int(max_retries)
    if retries < 0:
        raise ValueError("max_retries must be non-negative")
    return retries + 1


@dataclass(frozen=True, slots=True)
class LlmInvocationRuntime:
    purpose: str
    kind: str
    model: str | None = None
    base_url: str | None = None
    max_attempts: int = 1
    retry_backoff_seconds: float = 1.0
    invocation_timeout_seconds: float | None = None
    diagnostic_label: str | None = None
    limiter_registry: LimiterRegistry | None = None
    limiter_name: str = "llm_provider"
    sleep: SleepFn = time.sleep

    def invoke(
        self,
        *,
        request: dict[str, Any],
        call: ProviderCall,
        phase: str,
        debug_response: Callable[[Any], Any] | None = None,
    ) -> Any:
        if self.limiter_registry is None:
            return self._invoke_with_attempts(
                request=request,
                call=call,
                phase=phase,
                debug_response=debug_response,
            )
        return self.limiter_registry.sync_limiter(self.limiter_name).run(
            lambda: self._invoke_with_attempts(
                request=request,
                call=call,
                phase=phase,
                debug_response=debug_response,
            )
        )

    def _invoke_with_attempts(
        self,
        *,
        request: dict[str, Any],
        call: ProviderCall,
        phase: str,
        debug_response: Callable[[Any], Any] | None,
    ) -> Any:
        max_attempts = max(1, int(self.max_attempts))
        last_error: BaseException | None = None
        for attempt in range(1, max_attempts + 1):
            attempt_request = {
                **request,
                "invocation_kind": self.kind,
                "attempt": attempt,
                "max_attempts": max_attempts,
            }
            span = get_llm_debug_recorder().begin(
                purpose=self.purpose,
                kind=self.kind,
                model=self.model,
                base_url=self.base_url,
                request_context=current_llm_debug_context(),
                request=attempt_request,
            )
            try:
                response = self._call_provider(
                    f"{phase} attempt={attempt}",
                    call,
                )
            except Exception as exc:
                classification = classify_llm_provider_error(exc)
                retryable = classification.retryable and attempt < max_attempts
                backoff_seconds = (
                    _retry_delay_seconds(
                        classification,
                        default_backoff_seconds=self.retry_backoff_seconds * attempt,
                    )
                    if retryable
                    else None
                )
                span.finish(
                    error=exc,
                    metadata={
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "retry_reason": classification.reason if retryable else None,
                        "backoff_seconds": backoff_seconds,
                        "provider_status": classification.status_code,
                        "error_taxonomy": classification.to_dict(),
                        "final_status": "retrying" if retryable else "failed",
                        "usage": None,
                    },
                )
                last_error = exc
                if not retryable:
                    raise LlmProviderInvocationError(
                        _invocation_error_message(
                            exc,
                            classification=classification,
                        ),
                        classification=classification,
                        original=exc,
                    ) from exc
                if backoff_seconds:
                    self.sleep(backoff_seconds)
                continue

            usage = extract_llm_usage(response)
            span.finish(
                response=response if debug_response is None else debug_response(response),
                metadata={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "retry_reason": None,
                    "backoff_seconds": None,
                    "provider_status": None,
                    "error_taxonomy": None,
                    "final_status": "succeeded",
                    "usage": usage,
                },
            )
            return response

        assert last_error is not None
        classification = classify_llm_provider_error(last_error)
        raise LlmProviderInvocationError(
            _invocation_error_message(last_error, classification=classification),
            classification=classification,
            original=last_error,
        ) from last_error

    def _call_provider(self, phase: str, call: ProviderCall) -> Any:
        if self.diagnostic_label is None or self.invocation_timeout_seconds is None:
            return call()
        if threading.current_thread() is not threading.main_thread():
            self._log_stage(
                f"LLM provider timeout not armed outside main thread phase={phase!r}"
            )
            return call()
        with LiveStageTimeout(
            phase,
            self.invocation_timeout_seconds,
            hard_exit=False,
        ):
            return call()

    def _log_stage(self, message: str) -> None:
        if self.diagnostic_label is None:
            return
        print(f"[{self.diagnostic_label}] {message}", flush=True)


def extract_llm_usage(response: Any) -> dict[str, Any] | None:
    for attr in ("usage_metadata", "usage", "token_usage"):
        if hasattr(response, attr):
            try:
                value = getattr(response, attr)
            except Exception:
                continue
            usage = _coerce_usage(value)
            if usage:
                return usage
    if hasattr(response, "response_metadata"):
        try:
            metadata = getattr(response, "response_metadata")
        except Exception:
            metadata = None
        if isinstance(metadata, dict):
            for key in ("token_usage", "usage"):
                usage = _coerce_usage(metadata.get(key))
                if usage:
                    return usage
    if hasattr(response, "model_dump"):
        try:
            payload = response.model_dump()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            usage = _usage_from_mapping(payload)
            if usage:
                return usage
    if isinstance(response, dict):
        return _usage_from_mapping(response)
    return None


def _coerce_usage(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return serialize_llm_payload(value)
    if hasattr(value, "model_dump"):
        try:
            payload = value.model_dump()
        except Exception:
            return None
        return serialize_llm_payload(payload) if isinstance(payload, dict) else None
    return None


def _usage_from_mapping(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("usage", "usage_metadata", "token_usage"):
        usage = _coerce_usage(payload.get(key))
        if usage:
            return usage
    return None


def _exception_chain(exc: BaseException) -> tuple[BaseException, ...]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        item = stack.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        chain.append(item)
        for next_item in (item.__cause__, item.__context__):
            if next_item is not None:
                stack.append(next_item)
    return tuple(chain)


def _classify_single_error(exc: BaseException) -> LlmProviderErrorClassification:
    status_code = _status_code(exc)
    error_payload = _error_payload(exc)
    error_type = _string_field(exc, "type") or _nested_error_field(error_payload, "type")
    error_code = _string_field(exc, "code") or _nested_error_field(error_payload, "code")
    error_param = _string_field(exc, "param") or _nested_error_field(error_payload, "param")
    retry_after = _retry_after_seconds(exc, error_payload)
    text = _error_text(exc, error_payload)

    if _is_timeout_error(exc):
        return LlmProviderErrorClassification(
            category="transport_timeout",
            retryable=True,
            reason="transport_timeout",
            retry_after_seconds=retry_after,
            error_type=error_type,
            error_code=error_code,
            error_param=error_param,
        )
    if _is_connection_error(exc):
        return LlmProviderErrorClassification(
            category="transport_connection",
            retryable=True,
            reason="transport_connection",
            retry_after_seconds=retry_after,
            error_type=error_type,
            error_code=error_code,
            error_param=error_param,
        )

    if status_code in {500, 502, 503, 504}:
        return LlmProviderErrorClassification(
            category="transient_http",
            retryable=True,
            reason=f"http_{status_code}",
            status_code=status_code,
            retry_after_seconds=retry_after,
            error_type=error_type,
            error_code=error_code,
            error_param=error_param,
        )

    if status_code == 429:
        if _looks_like_usage_or_quota_error(text, error_type, error_code):
            return LlmProviderErrorClassification(
                category="rate_limit_usage_or_quota",
                retryable=False,
                reason="usage_or_quota_rate_limit",
                status_code=status_code,
                retry_after_seconds=retry_after,
                error_type=error_type,
                error_code=error_code,
                error_param=error_param,
            )
        retryable = retry_after is not None or _looks_like_transient_rate_limit(
            text,
            error_type,
            error_code,
        )
        return LlmProviderErrorClassification(
            category="rate_limit_transient"
            if retryable
            else "rate_limit_not_retryable",
            retryable=retryable,
            reason="retry_after_rate_limit"
            if retry_after is not None
            else (
                "transient_rate_limit" if retryable else "rate_limit_without_retry_signal"
            ),
            status_code=status_code,
            retry_after_seconds=retry_after,
            error_type=error_type,
            error_code=error_code,
            error_param=error_param,
        )

    if status_code in {400, 401, 403}:
        return LlmProviderErrorClassification(
            category="invalid_or_auth_request",
            retryable=False,
            reason=f"http_{status_code}_non_retryable",
            status_code=status_code,
            retry_after_seconds=retry_after,
            error_type=error_type,
            error_code=error_code,
            error_param=error_param,
        )
    if _looks_like_context_window_error(text, error_type, error_code):
        return LlmProviderErrorClassification(
            category="context_window_exceeded",
            retryable=False,
            reason="context_window_exceeded",
            status_code=status_code,
            retry_after_seconds=retry_after,
            error_type=error_type,
            error_code=error_code,
            error_param=error_param,
        )
    if _looks_like_schema_or_tool_error(text, error_type, error_code):
        return LlmProviderErrorClassification(
            category="schema_or_tool_error",
            retryable=False,
            reason="schema_or_tool_error",
            status_code=status_code,
            retry_after_seconds=retry_after,
            error_type=error_type,
            error_code=error_code,
            error_param=error_param,
        )
    if status_code is not None:
        return LlmProviderErrorClassification(
            category="http_non_retryable",
            retryable=False,
            reason=f"http_{status_code}_non_retryable",
            status_code=status_code,
            retry_after_seconds=retry_after,
            error_type=error_type,
            error_code=error_code,
            error_param=error_param,
        )
    return LlmProviderErrorClassification(
        category="unknown_provider_error",
        retryable=False,
        reason="unknown_provider_error",
        retry_after_seconds=retry_after,
        error_type=error_type,
        error_code=error_code,
        error_param=error_param,
    )


def _status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    for attr in ("status_code", "status"):
        value = getattr(response, attr, None)
        if isinstance(value, int):
            return value
    code = getattr(exc, "code", None)
    return code if isinstance(code, int) else None


def _error_payload(exc: BaseException) -> Any:
    body = getattr(exc, "body", None)
    if body is not None:
        return _parse_payload(body)
    response = getattr(exc, "response", None)
    if response is not None:
        json_method = getattr(response, "json", None)
        if callable(json_method):
            try:
                return json_method()
            except Exception:
                pass
        text = getattr(response, "text", None)
        if text is not None:
            return _parse_payload(text)
    return None


def _parse_payload(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _nested_error_field(payload: Any, field: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    candidates = [payload.get(field)]
    error = payload.get("error")
    if isinstance(error, dict):
        candidates.append(error.get(field))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _string_field(exc: BaseException, field: str) -> str | None:
    value = getattr(exc, field, None)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _retry_after_seconds(
    exc: BaseException,
    payload: Any,
) -> float | None:
    for attr in (
        "retry_after",
        "retry_after_seconds",
        "retry_after_ms",
        "requested_delay",
    ):
        delay = _parse_retry_after(getattr(exc, attr, None), milliseconds=attr.endswith("_ms"))
        if delay is not None:
            return delay
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        for key in ("retry-after", "Retry-After"):
            try:
                value = headers.get(key)
            except Exception:
                value = None
            delay = _parse_retry_after(value)
            if delay is not None:
                return delay
    return _retry_after_from_payload(payload)


def _retry_after_from_payload(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    candidates = [
        ("retry_after", False),
        ("retry_after_seconds", False),
        ("retry_after_ms", True),
    ]
    error = payload.get("error")
    mappings = [payload, error] if isinstance(error, dict) else [payload]
    for mapping in mappings:
        for key, milliseconds in candidates:
            delay = _parse_retry_after(mapping.get(key), milliseconds=milliseconds)
            if delay is not None:
                return delay
    return None


def _parse_retry_after(value: Any, *, milliseconds: bool = False) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        delay = float(value)
        return max(0.0, delay / 1000.0 if milliseconds else delay)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            delay = float(stripped)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(stripped)
            except (TypeError, ValueError):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            delay = (parsed - datetime.now(UTC)).total_seconds()
        return max(0.0, delay / 1000.0 if milliseconds else delay)
    return None


def _error_text(exc: BaseException, payload: Any) -> str:
    parts = [str(exc)]
    if isinstance(payload, str):
        parts.append(payload)
    elif isinstance(payload, dict):
        for field in ("message", "type", "code"):
            value = payload.get(field)
            if isinstance(value, str):
                parts.append(value)
        error = payload.get("error")
        if isinstance(error, dict):
            for field in ("message", "type", "code"):
                value = error.get(field)
                if isinstance(value, str):
                    parts.append(value)
    return " ".join(parts).lower()


def _looks_like_usage_or_quota_error(
    text: str,
    error_type: str | None,
    error_code: str | None,
) -> bool:
    combined = " ".join(filter(None, [text, error_type, error_code])).lower()
    markers = (
        "usage_limit",
        "usage limit",
        "quota",
        "insufficient_quota",
        "billing",
        "payment",
        "usage_not_included",
        "hard limit",
        "credit",
        "context_length_exceeded",
        "context window",
        "maximum context length",
        "invalid_request",
        "invalid request",
    )
    return any(marker in combined for marker in markers)


def _looks_like_transient_rate_limit(
    text: str,
    error_type: str | None,
    error_code: str | None,
) -> bool:
    combined = " ".join(filter(None, [text, error_type, error_code])).lower()
    markers = (
        "rate_limit",
        "rate limit",
        "too_many_requests",
        "too many requests",
        "throttle",
        "temporarily",
        "slow_down",
        "try again",
        "server_overloaded",
        "overloaded",
    )
    return any(marker in combined for marker in markers)


def _looks_like_context_window_error(
    text: str,
    error_type: str | None,
    error_code: str | None,
) -> bool:
    combined = " ".join(filter(None, [text, error_type, error_code])).lower()
    return any(
        marker in combined
        for marker in (
            "context_length_exceeded",
            "context window",
            "maximum context length",
            "too many tokens",
        )
    )


def _looks_like_schema_or_tool_error(
    text: str,
    error_type: str | None,
    error_code: str | None,
) -> bool:
    combined = " ".join(filter(None, [text, error_type, error_code])).lower()
    return any(
        marker in combined
        for marker in (
            "schema",
            "tool argument",
            "tool_call",
            "invalid tool",
            "invalid_request",
            "invalid request",
            "messages parameter",
            "messages 参数",
        )
    )


def _is_timeout_error(exc: BaseException) -> bool:
    try:
        from openai import APITimeoutError
    except ImportError:
        APITimeoutError = ()  # type: ignore[assignment]
    timeout_types: tuple[type[BaseException], ...] = (TimeoutError,)
    if isinstance(APITimeoutError, type):
        timeout_types = (*timeout_types, APITimeoutError)
    return isinstance(exc, timeout_types)


def _is_connection_error(exc: BaseException) -> bool:
    try:
        from openai import APIConnectionError
    except ImportError:
        APIConnectionError = ()  # type: ignore[assignment]
    connection_types: tuple[type[BaseException], ...] = (
        ConnectionError,
        urllib.error.URLError,
    )
    if isinstance(APIConnectionError, type):
        connection_types = (*connection_types, APIConnectionError)
    return isinstance(exc, connection_types)


def _retry_delay_seconds(
    classification: LlmProviderErrorClassification,
    *,
    default_backoff_seconds: float,
) -> float:
    if classification.retry_after_seconds is not None:
        return classification.retry_after_seconds
    return max(0.0, default_backoff_seconds)


def _invocation_error_message(
    exc: BaseException,
    *,
    classification: LlmProviderErrorClassification,
) -> str:
    return (
        f"LLM provider invocation failed "
        f"category={classification.category} "
        f"retryable={classification.retryable}: "
        f"{exc}"
    )


__all__ = [
    "LlmInvocationRuntime",
    "LlmProviderErrorClassification",
    "LlmProviderInvocationError",
    "classify_llm_provider_error",
    "extract_llm_usage",
    "is_retryable_llm_provider_error",
    "max_attempts_from_retries",
]
