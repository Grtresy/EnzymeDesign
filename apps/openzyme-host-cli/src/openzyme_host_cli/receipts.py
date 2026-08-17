from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from openzyme_runtime import sanitize_public_diagnostic_payload


PUBLIC_API_RECEIPT_V2_FIELDS = {
    "schema_id",
    "sequence",
    "method",
    "route",
    "status_code",
    "request_digest",
    "request",
    "response_digest",
    "response_semantic_digest",
}
PUBLIC_API_RECEIPT_FIELDS = PUBLIC_API_RECEIPT_V2_FIELDS | {
    "idempotency_key",
    "request_identity_digest",
    "effect_certainty",
    "retry_eligibility",
    "reconciliation_required",
    "terminal_scope",
}
PUBLIC_API_RECEIPT_SCHEMA_ID = "openzyme_public_api_receipt@3"
HISTORICAL_PUBLIC_API_RECEIPT_SCHEMA_IDS = frozenset({"openzyme_public_api_receipt@2"})
PUBLIC_RESPONSE_ENVELOPE_SCHEMA_ID = "openzyme_public_host_response@1"
MAX_PUBLIC_RECEIPT_CHAIN_BYTES = 8 * 1024 * 1024
MAX_PUBLIC_RECEIPT_RECORDS = 512
MAX_PUBLIC_RESPONSE_BYTES = 8 * 1024 * 1024


class PublicReceiptError(ValueError):
    pass


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def canonical_digest(payload: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _content_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _receipt_effect(method: str, status_code: int) -> dict[str, object]:
    if method == "GET":
        return {
            "effect_certainty": "no_effect",
            "retry_eligibility": "terminal",
            "reconciliation_required": False,
            "terminal_scope": "host_read_occurrence",
        }
    if 200 <= status_code < 400:
        return {
            "effect_certainty": "terminal_known",
            "retry_eligibility": "terminal",
            "reconciliation_required": False,
            "terminal_scope": "host_mutation_occurrence",
        }
    return {
        "effect_certainty": "unproven",
        "retry_eligibility": "reconcile_required",
        "reconciliation_required": True,
        "terminal_scope": "host_mutation_occurrence",
    }


def validate_public_api_receipt(
    receipt: object, *, sequence: int | None = None
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise PublicReceiptError("public receipt must be one JSON object")
    value = dict(receipt)
    schema_id = value.get("schema_id")
    is_current = schema_id == PUBLIC_API_RECEIPT_SCHEMA_ID
    expected_fields = (
        PUBLIC_API_RECEIPT_FIELDS if is_current else PUBLIC_API_RECEIPT_V2_FIELDS
    )
    expected_sequence = value.get("sequence") if sequence is None else sequence
    if not all(
        (
            set(value) == expected_fields,
            is_current or schema_id in HISTORICAL_PUBLIC_API_RECEIPT_SCHEMA_IDS,
            type(expected_sequence) is int and expected_sequence > 0,
            value.get("sequence") == expected_sequence,
            value.get("method") in {"GET", "POST", "PATCH"},
            str(value.get("route") or "").startswith("/v3/"),
            type(value.get("status_code")) is int,
            value.get("request_digest") == canonical_digest(value.get("request")),
            all(
                _is_digest(value.get(name))
                for name in (
                    "request_digest",
                    "response_digest",
                    "response_semantic_digest",
                )
            ),
        )
    ):
        raise PublicReceiptError("public receipt is noncanonical or discontinuous")
    if is_current:
        method = str(value["method"])
        idempotency_key = value.get("idempotency_key")
        expected_effect = _receipt_effect(method, int(value["status_code"]))
        request_identity = {
            "method": method,
            "route": value["route"],
            "request_digest": value["request_digest"],
            "idempotency_key": idempotency_key,
        }
        if not all(
            (
                (method == "GET" and idempotency_key is None)
                or (
                    method != "GET"
                    and isinstance(idempotency_key, str)
                    and bool(idempotency_key)
                ),
                value.get("request_identity_digest")
                == canonical_digest(request_identity),
                _is_digest(value.get("request_identity_digest")),
                all(
                    value.get(key) == expected
                    for key, expected in expected_effect.items()
                ),
            )
        ):
            raise PublicReceiptError(
                "public receipt effect or request identity is invalid"
            )
    return value


def parse_sse_events(content: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in content.splitlines():
        if not line.startswith("data:"):
            continue
        value = json.loads(line.removeprefix("data:").strip())
        if not isinstance(value, dict):
            raise PublicReceiptError("Host event stream data must be JSON objects")
        events.append(dict(value))
    return events


def _request_semantics(
    method: str, route: str, body: Mapping[str, Any] | None
) -> dict[str, Any]:
    if method == "GET":
        if "?replay=1&after_cursor=" not in route:
            return {}
        try:
            return {"replay": True, "after_cursor": int(route.rsplit("=", 1)[1])}
        except ValueError as exc:
            raise PublicReceiptError("event replay cursor is invalid") from exc
    value = dict(body or {})
    if not route.endswith("/messages"):
        return value
    message, skills = value.get("message"), value.get("skill_keys") or []
    task_id, lane_id = value.get("task_id"), value.get("lane_id")
    if not all(
        (
            isinstance(message, str),
            isinstance(skills, list),
            isinstance(skills, list)
            and all(isinstance(item, str) and item for item in skills),
            task_id is None or isinstance(task_id, str),
            lane_id is None or isinstance(lane_id, str),
        )
    ):
        raise PublicReceiptError("message receipt input is malformed")
    return {
        "message_digest": _content_digest(message.encode()),
        "skill_keys": list(skills),
        "task_id": task_id,
        "lane_id": lane_id,
    }


def _response_semantics(route: str, response: Any) -> object:
    if "?replay=1&after_cursor=" in route:
        value: object = parse_sse_events(str(response.text))
    else:
        try:
            value = response.json()
        except Exception:
            value = str(response.text)
    return (
        sanitize_public_diagnostic_payload(value)
        if int(response.status_code) >= 400
        else value
    )


def _secure_target(path: Path) -> tuple[Path, Path]:
    target = path.expanduser().absolute()
    parent = target.parent.resolve(strict=True)
    if target.parent != parent or parent.is_symlink() or not parent.is_dir():
        raise PublicReceiptError("receipt parent must be one existing real directory")
    return target, parent


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        count = os.write(descriptor, content[offset:])
        if count <= 0:
            raise OSError("public receipt write made no progress")
        offset += count
    os.fsync(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_receipts(descriptor: int) -> list[dict[str, Any]]:
    if os.fstat(descriptor).st_size > MAX_PUBLIC_RECEIPT_CHAIN_BYTES:
        raise PublicReceiptError("public receipt chain exceeds its byte bound")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    content = b"".join(chunks)
    if content and not content.endswith(b"\n"):
        raise PublicReceiptError("public receipt chain has a truncated final record")
    records: list[dict[str, Any]] = []
    for sequence, line in enumerate(content.splitlines(), 1):
        if sequence > MAX_PUBLIC_RECEIPT_RECORDS:
            raise PublicReceiptError("public receipt chain exceeds its record bound")
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicReceiptError(
                "public receipt chain is not canonical JSONL"
            ) from exc
        if canonical_json_bytes(value) != line:
            raise PublicReceiptError(
                "public receipt chain is noncanonical or discontinuous"
            )
        records.append(validate_public_api_receipt(value, sequence=sequence))
    return records


def _require_current_receipts(records: list[dict[str, Any]]) -> None:
    if any(record.get("schema_id") != PUBLIC_API_RECEIPT_SCHEMA_ID for record in records):
        raise PublicReceiptError(
            "historical public receipt chains are read-only and cannot be extended"
        )


def require_current_public_receipt_chain(path: Path) -> None:
    """Reject a historical chain before issuing a current public request."""

    target, _ = _secure_target(path)
    try:
        descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
            raise PublicReceiptError(
                "public receipt chain must be one private regular file"
            )
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        _require_current_receipts(_read_receipts(descriptor))
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class _CanonicalJsonResponse:
    status_code: int
    payload: object

    @property
    def content(self) -> bytes:
        return canonical_json_bytes(self.payload)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def json(self) -> object:
        return self.payload


def append_public_api_receipt(
    path: Path,
    *,
    method: str,
    route: str,
    request_body: Mapping[str, Any] | None,
    response: Any,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _append_public_api_receipt(
        path,
        method=method,
        route=route,
        request_body=request_body,
        response=response,
        idempotency_key=idempotency_key,
        allow_reconciliation=False,
    )


def converge_public_api_mutation_receipt(
    path: Path,
    *,
    method: str,
    route: str,
    request_body: Mapping[str, Any],
    response_payload: object,
    status_code: int,
    idempotency_key: str,
) -> dict[str, Any]:
    """Append or converge terminal evidence after a source-owner observation."""

    if method not in {"POST", "PATCH"} or not 200 <= status_code < 400:
        raise PublicReceiptError(
            "only a terminal successful Host mutation can be reconciled"
        )
    return _append_public_api_receipt(
        path,
        method=method,
        route=route,
        request_body=request_body,
        response=_CanonicalJsonResponse(status_code, response_payload),
        idempotency_key=idempotency_key,
        allow_reconciliation=True,
    )


def _append_public_api_receipt(
    path: Path,
    *,
    method: str,
    route: str,
    request_body: Mapping[str, Any] | None,
    response: Any,
    idempotency_key: str | None,
    allow_reconciliation: bool,
) -> dict[str, Any]:
    target, parent = _secure_target(path)
    descriptor = os.open(
        target,
        os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
            raise PublicReceiptError(
                "public receipt chain must be one private regular file"
            )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        records = _read_receipts(descriptor)
        _require_current_receipts(records)
        current_size = os.fstat(descriptor).st_size
        raw = (
            response.content
            if isinstance(getattr(response, "content", None), bytes)
            else str(response.text).encode()
        )
        if len(raw) > MAX_PUBLIC_RESPONSE_BYTES:
            raise PublicReceiptError("Host response exceeds the public sealing bound")
        request = _request_semantics(method, route, request_body)
        effect = _receipt_effect(method, int(response.status_code))
        request_identity = {
            "method": method,
            "route": route,
            "request_digest": canonical_digest(request),
            "idempotency_key": idempotency_key,
        }
        receipt = {
            "schema_id": PUBLIC_API_RECEIPT_SCHEMA_ID,
            "sequence": len(records) + 1,
            "method": method,
            "route": route,
            "status_code": int(response.status_code),
            "request": request,
            "request_digest": canonical_digest(request),
            "idempotency_key": idempotency_key,
            "request_identity_digest": canonical_digest(request_identity),
            "response_digest": _content_digest(raw),
            "response_semantic_digest": canonical_digest(
                _response_semantics(route, response)
            ),
            **effect,
        }
        same_identity = [
            record
            for record in records
            if record.get("schema_id") == PUBLIC_API_RECEIPT_SCHEMA_ID
            and record.get("request_identity_digest")
            == receipt["request_identity_digest"]
        ]
        if allow_reconciliation:
            for existing in same_identity:
                if existing.get("effect_certainty") != "terminal_known":
                    continue
                if (
                    existing.get("status_code") == receipt["status_code"]
                    and existing.get("response_semantic_digest")
                    == receipt["response_semantic_digest"]
                ):
                    return dict(existing)
                raise PublicReceiptError(
                    "durable Host owner differs from terminal public evidence"
                )
        elif method != "GET" and records and (
            records[-1].get("schema_id") == PUBLIC_API_RECEIPT_SCHEMA_ID
            and records[-1].get("request_identity_digest")
            == receipt["request_identity_digest"]
        ):
            existing = dict(records[-1])
            comparable = {
                key: value for key, value in receipt.items() if key != "sequence"
            }
            if {
                key: value for key, value in existing.items() if key != "sequence"
            } != comparable:
                raise PublicReceiptError(
                    "idempotent Host response drift requires exact reconciliation"
                )
            return existing
        record = canonical_json_bytes(receipt) + b"\n"
        if len(records) >= MAX_PUBLIC_RECEIPT_RECORDS:
            raise PublicReceiptError("public receipt chain exceeds its record bound")
        if current_size + len(record) > MAX_PUBLIC_RECEIPT_CHAIN_BYTES:
            raise PublicReceiptError("public receipt chain exceeds its byte bound")
        _write_all(descriptor, record)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    _fsync_directory(parent)
    return receipt


def seal_public_response(
    path: Path, *, receipt: Mapping[str, Any], response: object
) -> dict[str, Any]:
    normalized = validate_public_api_receipt(receipt)
    response_bytes = canonical_json_bytes(response)
    if len(response_bytes) > MAX_PUBLIC_RESPONSE_BYTES:
        raise PublicReceiptError("Host response exceeds the public sealing bound")
    digest = canonical_digest(response)
    if normalized["response_semantic_digest"] != digest:
        raise PublicReceiptError(
            "sealed response does not reproduce its semantic digest"
        )
    payload = {
        "schema_id": PUBLIC_RESPONSE_ENVELOPE_SCHEMA_ID,
        "receipt": normalized,
        "response": response,
        "response_semantic_digest": digest,
    }
    envelope = {**payload, "envelope_digest": canonical_digest(payload)}
    target, parent = _secure_target(path)
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        _write_all(descriptor, canonical_json_bytes(envelope) + b"\n")
    finally:
        os.close(descriptor)
    _fsync_directory(parent)
    return envelope


def converge_public_response(
    path: Path, *, receipt: Mapping[str, Any], response: object
) -> dict[str, Any]:
    """Publish a sealed response or return the exact existing envelope."""

    try:
        return seal_public_response(path, receipt=receipt, response=response)
    except FileExistsError:
        target, _ = _secure_target(path)
        descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_mode & 0o077
                or info.st_size > MAX_PUBLIC_RESPONSE_BYTES
            ):
                raise PublicReceiptError(
                    "existing public response envelope is not private canonical evidence"
                )
            content = b""
            while chunk := os.read(descriptor, 1024 * 1024):
                content += chunk
        finally:
            os.close(descriptor)
        try:
            existing = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicReceiptError(
                "existing public response envelope is not canonical JSON"
            ) from exc
        expected_receipt = validate_public_api_receipt(receipt)
        response_digest = canonical_digest(response)
        payload = {
            "schema_id": PUBLIC_RESPONSE_ENVELOPE_SCHEMA_ID,
            "receipt": expected_receipt,
            "response": response,
            "response_semantic_digest": response_digest,
        }
        expected = {**payload, "envelope_digest": canonical_digest(payload)}
        if content != canonical_json_bytes(existing) + b"\n" or existing != expected:
            raise PublicReceiptError(
                "existing public response envelope differs from exact reconciliation"
            )
        return dict(existing)
