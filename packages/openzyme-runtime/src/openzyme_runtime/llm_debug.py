from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from itertools import count
import os
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import BaseModel


DEFAULT_LLM_DEBUG_MAX_RECORDS = 500

_context: ContextVar[dict[str, Any]] = ContextVar("openzyme_llm_debug_context", default={})


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _configured_capacity() -> int:
    raw = os.getenv("OPENZYME_LLM_DEBUG_MAX_RECORDS")
    if raw in {None, ""}:
        return DEFAULT_LLM_DEBUG_MAX_RECORDS
    try:
        return max(1, int(str(raw)))
    except ValueError:
        return DEFAULT_LLM_DEBUG_MAX_RECORDS


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            pass
    payload: dict[str, Any] = {"type": value.__class__.__name__}
    for attr in ("content", "tool_calls", "additional_kwargs", "response_metadata", "usage_metadata", "id", "name"):
        if hasattr(value, attr):
            try:
                payload[attr] = _jsonable(getattr(value, attr))
            except Exception:
                payload[attr] = repr(getattr(value, attr))
    if len(payload) > 1:
        return payload
    return repr(value)


def serialize_llm_payload(value: Any) -> Any:
    return _jsonable(value)


def serialize_llm_error(exc: Exception) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }
    for attr in ("status_code", "code", "type", "param"):
        if hasattr(exc, attr):
            try:
                payload[attr] = _jsonable(getattr(exc, attr))
            except Exception:
                payload[attr] = repr(getattr(exc, attr))
    return payload


@dataclass(slots=True)
class LlmDebugRecorder:
    max_records: int
    _records: list[dict[str, Any]] = field(init=False, repr=False)
    _lock: Lock = field(init=False, repr=False)
    _sequence: Any = field(init=False, repr=False)

    def __init__(self, max_records: int | None = None) -> None:
        self.max_records = max_records or _configured_capacity()
        self._records: list[dict[str, Any]] = []
        self._lock = Lock()
        self._sequence = count(1)

    def begin(
        self,
        *,
        purpose: str,
        kind: str,
        model: str | None,
        base_url: str | None,
        request: dict[str, Any],
        request_context: dict[str, Any] | None = None,
    ) -> "LlmDebugSpan":
        return LlmDebugSpan(
            recorder=self,
            purpose=purpose,
            kind=kind,
            model=model,
            base_url=base_url,
            request=request,
            request_context=request_context,
        )

    def list_records(
        self,
        *,
        limit: int = 100,
        purpose: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            records = list(reversed(self._records))
        filtered: list[dict[str, Any]] = []
        for record in records:
            context = dict(record.get("request_context") or {})
            if purpose and record.get("purpose") != purpose:
                continue
            if kind and record.get("kind") != kind:
                continue
            if status and record.get("status") != status:
                continue
            if session_id and context.get("session_id") != session_id:
                continue
            filtered.append(record)
            if len(filtered) >= max(1, limit):
                break
        return filtered

    def get_record(self, debug_id: str) -> dict[str, Any] | None:
        with self._lock:
            for record in self._records:
                if record.get("debug_id") == debug_id:
                    return dict(record)
        return None

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def _append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(record)
            overflow = len(self._records) - self.max_records
            if overflow > 0:
                del self._records[:overflow]

    def _next_order(self) -> int:
        return next(self._sequence)


@dataclass(slots=True)
class LlmDebugSpan:
    recorder: LlmDebugRecorder
    purpose: str
    kind: str
    model: str | None
    base_url: str | None
    request: dict[str, Any]
    request_context: dict[str, Any] | None = None
    debug_id: str = field(init=False)
    created_at: str = field(init=False)
    _started_at: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.debug_id = f"llmdbg_{uuid4().hex[:12]}"
        self.created_at = _utc_now_iso()
        self._started_at = perf_counter()

    def finish(self, *, response: Any = None, error: Exception | None = None) -> None:
        finished_at = _utc_now_iso()
        duration_ms = round((perf_counter() - self._started_at) * 1000, 3)
        record = {
            "debug_id": self.debug_id,
            "order": self.recorder._next_order(),
            "created_at": self.created_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "status": "error" if error is not None else "succeeded",
            "purpose": self.purpose,
            "kind": self.kind,
            "model": self.model,
            "base_url": self.base_url,
            "request_context": serialize_llm_payload(self.request_context or current_llm_debug_context()),
            "request": serialize_llm_payload(self.request),
            "response": None if error is not None else serialize_llm_payload(response),
            "error": None if error is None else serialize_llm_error(error),
        }
        self.recorder._append(record)


_recorder = LlmDebugRecorder()


def get_llm_debug_recorder() -> LlmDebugRecorder:
    return _recorder


def current_llm_debug_context() -> dict[str, Any]:
    return dict(_context.get() or {})


@contextmanager
def llm_debug_context(**values: Any):
    merged = {**current_llm_debug_context(), **{key: value for key, value in values.items() if value is not None}}
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


__all__ = [
    "DEFAULT_LLM_DEBUG_MAX_RECORDS",
    "LlmDebugRecorder",
    "current_llm_debug_context",
    "get_llm_debug_recorder",
    "llm_debug_context",
    "serialize_llm_payload",
]
