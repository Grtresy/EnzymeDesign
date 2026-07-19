from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import stat
import struct
import time
import zlib

import pytest

from openzyme_host_api import aox_cutover_cli
from openzyme_host_api import aox_browser_observation
from openzyme_host_api.aox_browser_observation import (
    BROWSER_OBSERVATION_CAPTURE_SCHEMA_ID,
)
from openzyme_host_api.aox_browser_observation import BrowserObservationReceiptError
from openzyme_host_api.aox_browser_observation import build_browser_observation_receipt
from openzyme_host_api.aox_browser_observation import load_json_object
from openzyme_host_api.aox_browser_observation import publish_browser_observation_receipt
from openzyme_host_api.aox_cutover_live import BROWSER_OBSERVATION_MODE
from openzyme_host_api.aox_cutover_live import BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID
from openzyme_host_api.aox_cutover_live import MANUAL_APPROVAL_HANDOFF_SCHEMA_ID
from openzyme_host_api.aox_cutover_live import canonical_digest


def _digest(value: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    idat = zlib.compress(bytes((0, 0)))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def _page_state() -> dict[str, object]:
    return {
        "session_id": "sess_browser_operator",
        "approval_id": "appr_browser_operator",
        "operation_id": "op_browser_operator",
        "operation_digest": _digest("operation"),
        "approval_present": False,
        "operation_status": "completed",
        "final_master_response_id": "msg_browser_operator",
        "report_id": "report_browser_operator",
        "report_status": "published",
        "scientific_evidence_digest": _digest("scientific-evidence"),
        "workspace_digest": _digest("workspace"),
        "workspace_response_binding": {"sequence": 7},
        "event_stream_digest": _digest("events"),
        "event_last_cursor": 8,
        "event_response_binding": {"sequence": 9},
    }


def _handoff(tmp_path: Path, *, not_before_ns: int | None = None) -> dict[str, object]:
    page_state = _page_state()
    return {
        "schema_id": MANUAL_APPROVAL_HANDOFF_SCHEMA_ID,
        "status": "ready_for_completion_observation",
        "session_id": page_state["session_id"],
        "hold_seconds": 60.0,
        "observation_submission_timeout_seconds": 180.0,
        "observation_ready_at_unix_ns": time.time_ns() - 60_000_000_000,
        "receipt_not_before_unix_ns": (
            time.time_ns() - 1 if not_before_ns is None else not_before_ns
        ),
        "receipt_write_protocol": "atomic no-replace install after not-before",
        "workspace_digest": page_state["workspace_digest"],
        "event_receipt": {},
        "expected_page_state": page_state,
        "expected_page_state_digest": canonical_digest(page_state),
        "browser_observation_mode": BROWSER_OBSERVATION_MODE,
        "browser_observation_receipt_schema_id": (
            BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID
        ),
        "sealed_page_url": "loopback://same-process/ui/?project_id=aox-blank-world-cutover",
        "host_process_id": os.getpid(),
        "served_ui_dist_digest": _digest("ui-dist"),
        "browser_observation_challenge": _digest("challenge"),
        "browser_observation_receipt_path": str(tmp_path / "observation.json"),
    }


def _capture() -> dict[str, object]:
    return {
        "schema_id": BROWSER_OBSERVATION_CAPTURE_SCHEMA_ID,
        "page_target_id": "chrome-page-r23",
        "command_id": "chrome-observation-r23",
        "console_messages": [
            {"level": "info", "source": "console-api", "message": "ready"}
        ],
        "devtools_calls": [
            {
                "method": method,
                "request": {"method": method, "page": "chrome-page-r23"},
                "response": {"ok": True, "ordinal": ordinal},
            }
            for ordinal, method in enumerate(
                (
                    "list_console_messages",
                    "evaluate_script",
                    "take_screenshot",
                ),
                start=1,
            )
        ],
    }


def test_builder_derives_exact_raw_receipt_from_handoff_and_chrome_capture(
    tmp_path: Path,
) -> None:
    handoff = _handoff(tmp_path)
    receipt = build_browser_observation_receipt(
        handoff=handoff,
        capture=_capture(),
        screenshot_png=_png(),
    )

    assert len(receipt) == 23
    assert receipt["schema_id"] == BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID
    assert receipt["page_state"] == handoff["expected_page_state"]
    assert receipt["page_state_digest"] == handoff["expected_page_state_digest"]
    assert receipt["application_error_count"] == 0
    assert receipt["screenshot_width"] == 1
    assert receipt["screenshot_height"] == 1
    assert [
        item["method"] for item in receipt["devtools_transcript"]  # type: ignore[index]
    ] == ["list_console_messages", "evaluate_script", "take_screenshot"]
    assert "host_observation_ready_at_unix_ns" not in receipt


def test_builder_refuses_error_console_instead_of_filtering_it(
    tmp_path: Path,
) -> None:
    capture = _capture()
    capture["console_messages"] = [
        {"level": "error", "source": "network", "message": "failed"}
    ]

    with pytest.raises(BrowserObservationReceiptError) as exc_info:
        build_browser_observation_receipt(
            handoff=_handoff(tmp_path),
            capture=capture,
            screenshot_png=_png(),
        )

    assert exc_info.value.code == "browser_observation_console_error"


def test_builder_rejects_non_string_console_message(tmp_path: Path) -> None:
    capture = _capture()
    capture["console_messages"] = [
        {"level": "info", "source": "console-api", "message": {"ready": True}}
    ]

    with pytest.raises(BrowserObservationReceiptError) as exc_info:
        build_browser_observation_receipt(
            handoff=_handoff(tmp_path),
            capture=capture,
            screenshot_png=_png(),
        )

    assert exc_info.value.code == "browser_observation_console_invalid"


def test_builder_rejects_page_state_or_devtools_schema_drift(
    tmp_path: Path,
) -> None:
    handoff = _handoff(tmp_path)
    handoff["expected_page_state"] = {
        **dict(handoff["expected_page_state"]),
        "legacy_state": True,
    }
    handoff["expected_page_state_digest"] = canonical_digest(
        handoff["expected_page_state"]
    )
    with pytest.raises(BrowserObservationReceiptError) as page_error:
        build_browser_observation_receipt(
            handoff=handoff,
            capture=_capture(),
            screenshot_png=_png(),
        )
    assert page_error.value.code == "browser_observation_handoff_invalid"

    capture = _capture()
    capture["devtools_calls"] = [
        *list(capture["devtools_calls"]),
        {"method": "extra_call", "request": {}, "response": {}},
    ]
    with pytest.raises(BrowserObservationReceiptError) as transcript_error:
        build_browser_observation_receipt(
            handoff=_handoff(tmp_path),
            capture=capture,
            screenshot_png=_png(),
        )
    assert transcript_error.value.code == "browser_observation_transcript_invalid"


def test_json_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    source = tmp_path / "capture.json"
    source.write_text(
        '{"schema_id":"first","schema_id":"second"}\n',
        encoding="utf-8",
    )

    with pytest.raises(BrowserObservationReceiptError) as exc_info:
        load_json_object(source, label="Chrome capture")

    assert exc_info.value.code == "browser_observation_input_invalid"


def test_json_loader_rejects_symlink_input(tmp_path: Path) -> None:
    source = tmp_path / "capture-source.json"
    source.write_text("{}\n", encoding="utf-8")
    linked = tmp_path / "capture.json"
    linked.symlink_to(source)

    with pytest.raises(BrowserObservationReceiptError) as exc_info:
        load_json_object(linked, label="Chrome capture")

    assert exc_info.value.code == "browser_observation_input_invalid"


def test_publisher_installs_mode_0600_after_not_before_without_temp_residue(
    tmp_path: Path,
) -> None:
    handoff = _handoff(tmp_path)
    receipt = build_browser_observation_receipt(
        handoff=handoff,
        capture=_capture(),
        screenshot_png=_png(),
    )

    target = publish_browser_observation_receipt(
        handoff=handoff,
        receipt=receipt,
        poll_interval_seconds=0.001,
    )

    assert json.loads(target.read_text(encoding="utf-8")) == receipt
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".observation.json.*.tmp"))


def test_publisher_never_replaces_a_target_that_appears_during_hold(
    tmp_path: Path,
) -> None:
    handoff = _handoff(tmp_path, not_before_ns=time.time_ns() + 1_000_000_000)
    target = Path(str(handoff["browser_observation_receipt_path"]))
    target.write_text("existing\n", encoding="utf-8")
    receipt = build_browser_observation_receipt(
        handoff=handoff,
        capture=_capture(),
        screenshot_png=_png(),
    )

    with pytest.raises(BrowserObservationReceiptError) as exc_info:
        publish_browser_observation_receipt(
            handoff=handoff,
            receipt=receipt,
            poll_interval_seconds=0.001,
        )

    assert exc_info.value.code == "browser_observation_receipt_too_early"
    assert target.read_text(encoding="utf-8") == "existing\n"


def test_publisher_wraps_staging_creation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = _handoff(tmp_path)
    receipt = build_browser_observation_receipt(
        handoff=handoff,
        capture=_capture(),
        screenshot_png=_png(),
    )

    def _fail_mkstemp(**_: object) -> tuple[int, str]:
        raise PermissionError("denied")

    monkeypatch.setattr(aox_browser_observation.tempfile, "mkstemp", _fail_mkstemp)

    with pytest.raises(BrowserObservationReceiptError) as exc_info:
        publish_browser_observation_receipt(
            handoff=handoff,
            receipt=receipt,
            poll_interval_seconds=0.001,
        )

    assert exc_info.value.code == "browser_observation_receipt_write_failed"
    assert exc_info.value.details == {"failure_type": "PermissionError"}


def test_browser_receipt_cli_publishes_challenged_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handoff = _handoff(tmp_path)
    handoff_path = tmp_path / "handoff.json"
    capture_path = tmp_path / "capture.json"
    screenshot_path = tmp_path / "page.png"
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
    capture_path.write_text(json.dumps(_capture()), encoding="utf-8")
    screenshot_path.write_bytes(_png())

    exit_code = aox_cutover_cli.main(
        [
            "browser-receipt",
            "--handoff",
            str(handoff_path),
            "--capture",
            str(capture_path),
            "--screenshot",
            str(screenshot_path),
            "--output",
            str(handoff["browser_observation_receipt_path"]),
            "--poll-interval-seconds",
            "0.001",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "published"
    assert output["raw_receipt_field_count"] == 23
    target = Path(str(handoff["browser_observation_receipt_path"]))
    assert len(json.loads(target.read_text(encoding="utf-8"))) == 23
    assert base64.b64decode(
        json.loads(target.read_text(encoding="utf-8"))["screenshot_png_base64"]
    ) == _png()
