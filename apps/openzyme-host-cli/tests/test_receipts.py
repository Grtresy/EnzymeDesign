from __future__ import annotations

import json
import hashlib
from pathlib import Path
import stat

import pytest

from openzyme_host_cli.receipts import PublicReceiptError
from openzyme_host_cli.receipts import append_public_api_receipt
from openzyme_host_cli.receipts import canonical_digest
from openzyme_host_cli.receipts import seal_public_response


class _Response:
    def __init__(self, status_code: int, payload: object, *, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = text.encode("utf-8")

    def json(self) -> object:
        return self._payload


def test_receipt_chain_is_private_contiguous_and_message_safe(tmp_path: Path) -> None:
    chain = tmp_path / "receipts.jsonl"
    first = append_public_api_receipt(
        chain,
        method="POST",
        route="/v3/sessions/sess/messages",
        request_body={
            "message": "private conductor instruction",
            "skill_keys": ["workflow:aox@1.0.0#sha256:" + "a" * 64],
        },
        response=_Response(200, {"status": "accepted"}),
    )
    second = append_public_api_receipt(
        chain,
        method="GET",
        route="/v3/sessions/sess/workspace",
        request_body=None,
        response=_Response(200, {"session": {"session_id": "sess"}}),
    )

    records = [json.loads(line) for line in chain.read_text().splitlines()]
    assert records == [first, second]
    assert [item["sequence"] for item in records] == [1, 2]
    assert first["request"] == {
        "message_digest": "sha256:"
        + hashlib.sha256(b"private conductor instruction").hexdigest(),
        "skill_keys": ["workflow:aox@1.0.0#sha256:" + "a" * 64],
        "task_id": None,
        "lane_id": None,
    }
    assert "private conductor instruction" not in chain.read_text()
    assert stat.S_IMODE(chain.stat().st_mode) == 0o600


def test_receipt_append_rejects_tamper_truncation_and_hardlinks(tmp_path: Path) -> None:
    chain = tmp_path / "receipts.jsonl"
    append_public_api_receipt(
        chain,
        method="GET",
        route="/v3/runtime/health",
        request_body=None,
        response=_Response(200, {"status": "ready"}),
    )
    original = chain.read_bytes()
    record = json.loads(original)
    record["request"] = {"tampered": True}
    chain.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(PublicReceiptError):
        append_public_api_receipt(
            chain,
            method="GET",
            route="/v3/runtime/health",
            request_body=None,
            response=_Response(200, {"status": "ready"}),
        )

    chain.write_bytes(original.removesuffix(b"\n"))
    with pytest.raises(PublicReceiptError):
        append_public_api_receipt(
            chain,
            method="GET",
            route="/v3/runtime/health",
            request_body=None,
            response=_Response(200, {"status": "ready"}),
        )

    chain.write_bytes(original)
    linked = tmp_path / "linked.jsonl"
    linked.hardlink_to(chain)
    with pytest.raises(PublicReceiptError):
        append_public_api_receipt(
            chain,
            method="GET",
            route="/v3/runtime/health",
            request_body=None,
            response=_Response(200, {"status": "ready"}),
        )


def test_failed_response_is_receipted_but_cannot_be_rewritten(tmp_path: Path) -> None:
    chain = tmp_path / "receipts.jsonl"
    receipt = append_public_api_receipt(
        chain,
        method="POST",
        route="/v3/sessions",
        request_body={"project_id": "p", "objective": "o"},
        response=_Response(409, {"error": {"code": "conflict"}}),
    )
    assert receipt["status_code"] == 409
    assert receipt["request_digest"] == canonical_digest(receipt["request"])

    response_path = tmp_path / "response.json"
    envelope = seal_public_response(
        response_path,
        receipt=receipt,
        response={"error": {"code": "conflict"}},
    )
    assert envelope["receipt"] == receipt
    assert stat.S_IMODE(response_path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        seal_public_response(
            response_path,
            receipt=receipt,
            response={"error": {"code": "conflict"}},
        )
    with pytest.raises(PublicReceiptError):
        seal_public_response(
            tmp_path / "different.json",
            receipt=receipt,
            response={"error": {"code": "different"}},
        )


def test_event_response_seals_parsed_sse_semantics(tmp_path: Path) -> None:
    chain = tmp_path / "receipts.jsonl"
    response = _Response(
        200,
        None,
        text=(
            "event: openzyme.event\n"
            'data: {"cursor":1,"event_type":"session.created"}\n\n'
        ),
    )
    receipt = append_public_api_receipt(
        chain,
        method="GET",
        route="/v3/sessions/sess/events?replay=1&after_cursor=0",
        request_body=None,
        response=response,
    )
    sealed = seal_public_response(
        tmp_path / "events.json",
        receipt=receipt,
        response=[{"cursor": 1, "event_type": "session.created"}],
    )
    assert sealed["response_semantic_digest"] == receipt[
        "response_semantic_digest"
    ]
