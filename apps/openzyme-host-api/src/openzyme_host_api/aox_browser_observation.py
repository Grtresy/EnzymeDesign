from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import zlib

from openzyme_runtime import REPO_ROOT

from .aox_cutover_evidence import canonical_digest


BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID = "aox_browser_observation_receipt@2"
BROWSER_OBSERVATION_MODE = "chrome_devtools_mcp_file_handoff"
BROWSER_OBSERVATION_CAPTURE_SCHEMA_ID = "aox_browser_observation_capture@1"
MANUAL_APPROVAL_HANDOFF_SCHEMA_ID = "aox_manual_approval_handoff@1"
_MAX_BROWSER_SCREENSHOT_BASE64_CHARS = 64 * 1024 * 1024
_MAX_BROWSER_SCREENSHOT_DECODED_BYTES = 64 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_CAPTURE_FIELDS = frozenset(
    {
        "schema_id",
        "page_target_id",
        "command_id",
        "console_messages",
        "devtools_calls",
    }
)
_EXPECTED_PAGE_STATE_FIELDS = frozenset(
    {
        "session_id",
        "approval_id",
        "operation_id",
        "operation_digest",
        "approval_present",
        "operation_status",
        "final_master_response_id",
        "report_id",
        "report_status",
        "scientific_evidence_digest",
        "workspace_digest",
        "workspace_response_binding",
        "event_stream_digest",
        "event_last_cursor",
        "event_response_binding",
    }
)
_REQUIRED_DEVTOOLS_METHODS = (
    "list_console_messages",
    "evaluate_script",
    "take_screenshot",
)
_RAW_RECEIPT_FIELDS = frozenset(
    {
        "schema_id",
        "observation_mode",
        "observation_challenge",
        "session_id",
        "approval_id",
        "operation_id",
        "page_url",
        "host_process_id",
        "served_ui_dist_digest",
        "page_target_id",
        "observation_window_seconds",
        "console_entries",
        "console_entries_digest",
        "application_error_count",
        "page_state",
        "page_state_digest",
        "devtools_command_receipt",
        "devtools_transcript",
        "devtools_transcript_digest",
        "screenshot_png_base64",
        "screenshot_digest",
        "screenshot_width",
        "screenshot_height",
    }
)


class BrowserObservationReceiptError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = {} if details is None else dict(details)


def _strict_json_object(content: str) -> dict[str, object]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant is forbidden: {value}")

    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    parsed = json.loads(
        content,
        parse_constant=reject_constant,
        object_pairs_hook=pairs_hook,
    )
    if not isinstance(parsed, dict):
        raise ValueError("JSON receipt must be an object")
    return dict(parsed)


def _browser_screenshot_png(
    encoded: object,
) -> tuple[bytes, int, int] | None:
    if (
        not isinstance(encoded, str)
        or not encoded
        or len(encoded) > _MAX_BROWSER_SCREENSHOT_BASE64_CHARS
    ):
        return None
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return None
    if len(content) < 45 or content[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    offset = 8
    ihdr: bytes | None = None
    idat_parts: list[bytes] = []
    seen_iend = False
    seen_non_idat_after_idat = False
    while offset < len(content):
        if offset + 12 > len(content):
            return None
        length = int.from_bytes(content[offset : offset + 4], "big")
        chunk_type = content[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(content):
            return None
        data = content[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(content[offset + 8 + length : chunk_end], "big")
        if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != expected_crc:
            return None
        if chunk_type == b"IHDR":
            if ihdr is not None or offset != 8 or length != 13:
                return None
            ihdr = data
        elif chunk_type == b"IDAT":
            if ihdr is None or seen_iend or seen_non_idat_after_idat:
                return None
            idat_parts.append(data)
        elif chunk_type == b"IEND":
            if ihdr is None or not idat_parts or seen_iend or length != 0:
                return None
            seen_iend = True
            if chunk_end != len(content):
                return None
        elif idat_parts:
            seen_non_idat_after_idat = True
        offset = chunk_end
    if ihdr is None or not idat_parts or not seen_iend:
        return None
    width = int.from_bytes(ihdr[0:4], "big")
    height = int.from_bytes(ihdr[4:8], "big")
    bit_depth, color_type, compression, filter_method, interlace = ihdr[8:13]
    channels_by_color_type = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    valid_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    if (
        width <= 0
        or height <= 0
        or width > 16_384
        or height > 16_384
        or color_type not in channels_by_color_type
        or bit_depth not in valid_depths[color_type]
        or compression != 0
        or filter_method != 0
        or interlace != 0
    ):
        return None
    row_bytes = (width * channels_by_color_type[color_type] * bit_depth + 7) // 8
    expected_decoded_size = height * (1 + row_bytes)
    if expected_decoded_size > _MAX_BROWSER_SCREENSHOT_DECODED_BYTES:
        return None
    try:
        decompressor = zlib.decompressobj()
        pixels = decompressor.decompress(
            b"".join(idat_parts), expected_decoded_size + 1
        )
    except zlib.error:
        return None
    if (
        len(pixels) != expected_decoded_size
        or not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
        or any(
            pixels[row * (1 + row_bytes)] not in {0, 1, 2, 3, 4}
            for row in range(height)
        )
    ):
        return None
    return content, width, height


def load_json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        content = _read_regular_non_symlink(
            path,
            label=label,
            error_code="browser_observation_input_invalid",
        )
        payload = _strict_json_object(content.decode("utf-8"))
    except BrowserObservationReceiptError:
        raise
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise BrowserObservationReceiptError(
            "browser_observation_input_invalid",
            f"{label} must contain one strict UTF-8 JSON object",
            details={"failure_type": type(exc).__name__},
        ) from exc
    return dict(payload)


def load_screenshot_png(path: Path) -> bytes:
    content = _read_regular_non_symlink(
        path,
        label="screenshot PNG",
        error_code="browser_observation_screenshot_invalid",
    )
    encoded = base64.b64encode(content).decode("ascii")
    if _browser_screenshot_png(encoded) is None:
        raise BrowserObservationReceiptError(
            "browser_observation_screenshot_invalid",
            "screenshot bytes are not a canonical accepted PNG",
        )
    return content


def build_browser_observation_receipt(
    *,
    handoff: dict[str, object],
    capture: dict[str, object],
    screenshot_png: bytes,
) -> dict[str, object]:
    _validate_handoff(handoff)
    _validate_capture_shape(capture)
    page_state = dict(handoff["expected_page_state"])
    page_target_id = _required_text(capture.get("page_target_id"), "page_target_id")
    command_id = _required_text(capture.get("command_id"), "command_id")
    console_entries = _console_entries(capture.get("console_messages"))
    transcript = _devtools_transcript(
        capture.get("devtools_calls"),
        page_target_id=page_target_id,
    )
    screenshot_png_base64 = base64.b64encode(screenshot_png).decode("ascii")
    screenshot = _browser_screenshot_png(screenshot_png_base64)
    if screenshot is None:
        raise BrowserObservationReceiptError(
            "browser_observation_screenshot_invalid",
            "screenshot bytes are not a canonical accepted PNG",
        )
    screenshot_digest = "sha256:" + hashlib.sha256(screenshot[0]).hexdigest()
    transcript_digest = canonical_digest(transcript)
    command_digest = canonical_digest(
        {
            "tool": "chrome_devtools_mcp",
            "command_id": command_id,
            "page_target_id": page_target_id,
            "observation_challenge": handoff["browser_observation_challenge"],
            "action": "observe_console_page_state_and_screenshot",
        }
    )
    response_digest = canonical_digest(
        {
            "page_state": page_state,
            "console_entries": console_entries,
            "application_error_count": 0,
            "devtools_transcript_digest": transcript_digest,
            "screenshot_digest": screenshot_digest,
        }
    )
    receipt: dict[str, object] = {
        "schema_id": handoff["browser_observation_receipt_schema_id"],
        "observation_mode": handoff["browser_observation_mode"],
        "observation_challenge": handoff["browser_observation_challenge"],
        "session_id": handoff["session_id"],
        "approval_id": page_state["approval_id"],
        "operation_id": page_state["operation_id"],
        "page_url": handoff["sealed_page_url"],
        "host_process_id": handoff["host_process_id"],
        "served_ui_dist_digest": handoff["served_ui_dist_digest"],
        "page_target_id": page_target_id,
        "observation_window_seconds": handoff["hold_seconds"],
        "console_entries": console_entries,
        "console_entries_digest": canonical_digest(console_entries),
        "application_error_count": 0,
        "page_state": page_state,
        "page_state_digest": canonical_digest(page_state),
        "devtools_command_receipt": {
            "command_id": command_id,
            "tool": "chrome_devtools_mcp",
            "command_digest": command_digest,
            "response_digest": response_digest,
            "page_target_id": page_target_id,
        },
        "devtools_transcript": transcript,
        "devtools_transcript_digest": transcript_digest,
        "screenshot_png_base64": screenshot_png_base64,
        "screenshot_digest": screenshot_digest,
        "screenshot_width": screenshot[1],
        "screenshot_height": screenshot[2],
    }
    if set(receipt) != _RAW_RECEIPT_FIELDS:
        raise AssertionError("raw browser observation receipt field drift")
    return receipt


def publish_browser_observation_receipt(
    *,
    handoff: dict[str, object],
    receipt: dict[str, object],
    output: Path | None = None,
    poll_interval_seconds: float = 0.05,
) -> Path:
    _validate_handoff(handoff)
    if set(receipt) != _RAW_RECEIPT_FIELDS:
        raise BrowserObservationReceiptError(
            "browser_observation_receipt_invalid",
            "raw receipt must contain exactly the 23 operator fields",
        )
    if poll_interval_seconds <= 0 or poll_interval_seconds > 1:
        raise BrowserObservationReceiptError(
            "browser_observation_publish_config_invalid",
            "poll interval must be in the range (0, 1] seconds",
        )
    handoff_target = Path(
        _required_text(
            handoff.get("browser_observation_receipt_path"),
            "browser_observation_receipt_path",
        )
    )
    if not handoff_target.is_absolute():
        raise BrowserObservationReceiptError(
            "browser_observation_receipt_path_invalid",
            "Host handoff receipt target must be absolute",
        )
    requested_target = handoff_target if output is None else output
    if requested_target != handoff_target:
        raise BrowserObservationReceiptError(
            "browser_observation_receipt_path_mismatch",
            "operator output must match the exact Host handoff target",
        )
    target = _safe_output_target(requested_target)
    not_before_ns = _required_positive_int(
        handoff.get("receipt_not_before_unix_ns"),
        "receipt_not_before_unix_ns",
    )
    submission_seconds = _required_positive_number(
        handoff.get("observation_submission_timeout_seconds"),
        "observation_submission_timeout_seconds",
    )
    deadline_ns = not_before_ns + int(round(submission_seconds * 1_000_000_000))
    while time.time_ns() < not_before_ns:
        if os.path.lexists(target):
            raise BrowserObservationReceiptError(
                "browser_observation_receipt_too_early",
                "final receipt target appeared before the Host-held window ended",
            )
        remaining_seconds = (not_before_ns - time.time_ns()) / 1_000_000_000
        time.sleep(min(poll_interval_seconds, max(remaining_seconds, 0.001)))
    if time.time_ns() > deadline_ns:
        raise BrowserObservationReceiptError(
            "browser_observation_submission_timeout",
            "Host handoff submission deadline elapsed before publication",
        )
    if os.path.lexists(target):
        raise BrowserObservationReceiptError(
            "browser_observation_receipt_exists",
            "final receipt target is append-only and already exists",
        )
    content = (
        json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    descriptor = -1
    temporary: Path | None = None
    failure: BrowserObservationReceiptError | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("browser receipt write made no progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if time.time_ns() > deadline_ns:
            raise BrowserObservationReceiptError(
                "browser_observation_submission_timeout",
                "Host handoff submission deadline elapsed during publication",
            )
        # Atomic, no-replace installation. The final path and sibling temp
        # share one inode until the private temp name is removed.
        os.link(temporary, target, follow_symlinks=False)
        _fsync_directory(target.parent)
    except FileExistsError:
        failure = BrowserObservationReceiptError(
            "browser_observation_receipt_exists",
            "final receipt target raced with another writer",
        )
    except BrowserObservationReceiptError as exc:
        failure = exc
    except OSError as exc:
        failure = BrowserObservationReceiptError(
            "browser_observation_receipt_write_failed",
            "browser observation receipt could not be published durably",
            details={"failure_type": type(exc).__name__},
        )
    cleanup_failure: OSError | None = None
    if descriptor >= 0:
        try:
            os.close(descriptor)
        except OSError as exc:
            cleanup_failure = exc
    if temporary is not None:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as exc:
            cleanup_failure = cleanup_failure or exc
        try:
            _fsync_directory(target.parent)
        except OSError as exc:
            cleanup_failure = cleanup_failure or exc
    if failure is not None:
        raise failure
    if cleanup_failure is not None:
        raise BrowserObservationReceiptError(
            "browser_observation_receipt_write_failed",
            "browser observation receipt cleanup could not be completed durably",
            details={"failure_type": type(cleanup_failure).__name__},
        ) from cleanup_failure
    return target


def _validate_handoff(handoff: dict[str, object]) -> None:
    if (
        handoff.get("schema_id") != MANUAL_APPROVAL_HANDOFF_SCHEMA_ID
        or handoff.get("status") != "ready_for_completion_observation"
        or handoff.get("browser_observation_receipt_schema_id")
        != BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID
        or handoff.get("browser_observation_mode") != BROWSER_OBSERVATION_MODE
    ):
        raise BrowserObservationReceiptError(
            "browser_observation_handoff_invalid",
            "input is not the exact terminal Chrome observation handoff",
        )
    page_state = handoff.get("expected_page_state")
    if not isinstance(page_state, dict):
        raise BrowserObservationReceiptError(
            "browser_observation_handoff_invalid",
            "handoff expected_page_state must be an object",
        )
    page_state_payload = dict(page_state)
    if set(page_state_payload) != _EXPECTED_PAGE_STATE_FIELDS:
        raise BrowserObservationReceiptError(
            "browser_observation_handoff_invalid",
            "handoff expected_page_state field set has drifted",
        )
    for key in ("session_id", "approval_id", "operation_id"):
        _required_text(page_state_payload.get(key), f"expected_page_state.{key}")
    if page_state_payload["session_id"] != handoff.get("session_id"):
        raise BrowserObservationReceiptError(
            "browser_observation_handoff_invalid",
            "handoff session identity does not match expected page state",
        )
    if handoff.get("expected_page_state_digest") != canonical_digest(
        page_state_payload
    ):
        raise BrowserObservationReceiptError(
            "browser_observation_handoff_invalid",
            "handoff expected page-state digest does not match its payload",
        )
    _required_text(handoff.get("sealed_page_url"), "sealed_page_url")
    _required_positive_int(handoff.get("host_process_id"), "host_process_id")
    for key in ("served_ui_dist_digest", "browser_observation_challenge"):
        value = _required_text(handoff.get(key), key)
        if _SHA256_PATTERN.fullmatch(value) is None:
            raise BrowserObservationReceiptError(
                "browser_observation_handoff_invalid",
                f"{key} must be a canonical SHA-256 digest",
            )
    _required_positive_number(handoff.get("hold_seconds"), "hold_seconds")
    _required_positive_int(
        handoff.get("receipt_not_before_unix_ns"),
        "receipt_not_before_unix_ns",
    )
    _required_positive_number(
        handoff.get("observation_submission_timeout_seconds"),
        "observation_submission_timeout_seconds",
    )
    _required_text(
        handoff.get("browser_observation_receipt_path"),
        "browser_observation_receipt_path",
    )


def _validate_capture_shape(capture: dict[str, object]) -> None:
    if (
        set(capture) != _CAPTURE_FIELDS
        or capture.get("schema_id") != BROWSER_OBSERVATION_CAPTURE_SCHEMA_ID
    ):
        raise BrowserObservationReceiptError(
            "browser_observation_capture_invalid",
            "capture must match the exact trusted-operator input schema",
        )


def _console_entries(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise BrowserObservationReceiptError(
            "browser_observation_console_invalid",
            "console_messages must be a list",
        )
    entries: list[dict[str, object]] = []
    level_aliases = {"warn": "warning", "verbose": "debug"}
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict) or set(raw) != {"level", "source", "message"}:
            raise BrowserObservationReceiptError(
                "browser_observation_console_invalid",
                "each console message must contain only level, source, and message",
            )
        level = str(raw.get("level") or "").strip().lower()
        level = level_aliases.get(level, level)
        if level not in {"debug", "info", "log", "warning"}:
            raise BrowserObservationReceiptError(
                "browser_observation_console_error",
                "Chrome observation contains an application error or unsupported level",
                details={"level": level, "sequence": index},
            )
        source = _required_text(raw.get("source"), "console source")
        message_value = raw.get("message")
        if not isinstance(message_value, str):
            raise BrowserObservationReceiptError(
                "browser_observation_console_invalid",
                "each console message payload must be a string",
                details={"sequence": index},
            )
        entries.append(
            {
                "sequence": index,
                "level": level,
                "source": source,
                "message_digest": "sha256:"
                + hashlib.sha256(message_value.encode("utf-8")).hexdigest(),
            }
        )
    return entries


def _devtools_transcript(
    value: object,
    *,
    page_target_id: str,
) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise BrowserObservationReceiptError(
            "browser_observation_transcript_invalid",
            "devtools_calls must be a non-empty list",
        )
    transcript: list[dict[str, object]] = []
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict) or set(raw) != {"method", "request", "response"}:
            raise BrowserObservationReceiptError(
                "browser_observation_transcript_invalid",
                "each DevTools call must contain only method, request, and response",
            )
        method = _required_text(raw.get("method"), "DevTools method")
        try:
            request_digest = canonical_digest(raw.get("request"))
            response_digest = canonical_digest(raw.get("response"))
        except (TypeError, ValueError) as exc:
            raise BrowserObservationReceiptError(
                "browser_observation_transcript_invalid",
                "DevTools request and response must be canonical JSON values",
                details={"failure_type": type(exc).__name__, "method": method},
            ) from exc
        transcript.append(
            {
                "sequence": index,
                "tool": "chrome_devtools_mcp",
                "method": method,
                "page_target_id": page_target_id,
                "request_digest": request_digest,
                "response_digest": response_digest,
            }
        )
    if tuple(str(item["method"]) for item in transcript) != (
        _REQUIRED_DEVTOOLS_METHODS
    ):
        raise BrowserObservationReceiptError(
            "browser_observation_transcript_invalid",
            "DevTools transcript must contain the exact ordered console, page-state, and PNG calls",
        )
    return transcript


def _safe_output_target(path: Path) -> Path:
    expanded = path.expanduser()
    absolute = Path(os.path.abspath(expanded))
    try:
        parent = absolute.parent.resolve(strict=True)
    except OSError as exc:
        raise BrowserObservationReceiptError(
            "browser_observation_receipt_path_invalid",
            "receipt parent must be an existing real directory",
            details={"failure_type": type(exc).__name__},
        ) from exc
    if absolute.parent != parent or not parent.is_dir() or parent.is_symlink():
        raise BrowserObservationReceiptError(
            "browser_observation_receipt_path_invalid",
            "receipt parent must not traverse a symbolic link",
        )
    target = parent / absolute.name
    repo_root = REPO_ROOT.resolve()
    if target == repo_root or repo_root in target.parents:
        raise BrowserObservationReceiptError(
            "browser_observation_receipt_path_invalid",
            "browser observation receipt must be written outside the checkout",
        )
    if target.name in {"", ".", ".."}:
        raise BrowserObservationReceiptError(
            "browser_observation_receipt_path_invalid",
            "receipt target must have a safe filename",
        )
    return target


def _read_regular_non_symlink(
    path: Path,
    *,
    label: str,
    error_code: str,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    elif path.is_symlink():
        raise BrowserObservationReceiptError(
            error_code,
            f"{label} must be an existing regular non-symlink file",
        )
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise BrowserObservationReceiptError(
                error_code,
                f"{label} must be an existing regular non-symlink file",
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or len(content) != after.st_size:
            raise BrowserObservationReceiptError(
                error_code,
                f"{label} changed while it was being read",
            )
        return content
    except BrowserObservationReceiptError:
        raise
    except OSError as exc:
        raise BrowserObservationReceiptError(
            error_code,
            f"{label} must be an existing readable regular non-symlink file",
            details={"failure_type": type(exc).__name__},
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BrowserObservationReceiptError(
            "browser_observation_input_invalid",
            f"{label} must be a non-empty string",
        )
    return value.strip()


def _required_positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise BrowserObservationReceiptError(
            "browser_observation_input_invalid",
            f"{label} must be a positive integer",
        )
    return value


def _required_positive_number(value: object, label: str) -> float:
    if (
        type(value) not in {int, float}
        or not float(value) > 0
        or not float(value) < float("inf")
    ):
        raise BrowserObservationReceiptError(
            "browser_observation_input_invalid",
            f"{label} must be a positive finite number",
        )
    return float(value)


__all__ = [
    "BROWSER_OBSERVATION_CAPTURE_SCHEMA_ID",
    "BrowserObservationReceiptError",
    "build_browser_observation_receipt",
    "load_json_object",
    "load_screenshot_png",
    "publish_browser_observation_receipt",
]
