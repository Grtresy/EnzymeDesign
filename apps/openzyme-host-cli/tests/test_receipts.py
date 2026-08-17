from __future__ import annotations

import json
import hashlib
from pathlib import Path
import stat

import pytest

from openzyme_host_cli import receipts
from openzyme_host_cli.receipts import PublicReceiptError
from openzyme_host_cli.receipts import append_public_api_receipt
from openzyme_host_cli.receipts import canonical_digest
from openzyme_host_cli.receipts import canonical_json_bytes
from openzyme_host_cli.receipts import converge_public_api_mutation_receipt
from openzyme_host_cli.receipts import converge_public_response
from openzyme_host_cli.receipts import require_current_public_receipt_chain
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
        idempotency_key="test-message-1",
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
        idempotency_key="test-session-conflict",
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
    assert sealed["response_semantic_digest"] == receipt["response_semantic_digest"]


def test_failed_response_receipt_and_seal_share_sanitized_semantics(
    tmp_path: Path,
) -> None:
    chain = tmp_path / "receipts.jsonl"
    response = _Response(
        403,
        {
            "error": {
                "code": "forbidden",
                "message": "failed at /home/private/provider.json",
                "details": {"api_key": "sk-private"},
            }
        },
    )

    receipt = append_public_api_receipt(
        chain,
        method="GET",
        route="/v3/sessions/sess/workspace",
        request_body=None,
        response=response,
    )
    public_error = {
        "error": {
            "code": "forbidden",
            "message": "failed at [redacted-host-path]",
            "details": {},
        }
    }
    sealed = seal_public_response(
        tmp_path / "failed-response.json",
        receipt=receipt,
        response=public_error,
    )

    assert sealed["response"] == public_error
    assert receipt["response_semantic_digest"] == canonical_digest(public_error)
    assert "/home/private" not in chain.read_text(encoding="utf-8")
    assert "sk-private" not in chain.read_text(encoding="utf-8")


def test_receipt_and_response_bounds_fail_before_append_or_seal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = tmp_path / "bounded.jsonl"
    monkeypatch.setattr(receipts, "MAX_PUBLIC_RECEIPT_RECORDS", 1)
    first = append_public_api_receipt(
        chain,
        method="GET",
        route="/v3/runtime/health",
        request_body=None,
        response=_Response(200, {"status": "ready"}),
    )
    original = chain.read_bytes()
    with pytest.raises(PublicReceiptError, match="record bound"):
        append_public_api_receipt(
            chain,
            method="GET",
            route="/v3/runtime/health",
            request_body=None,
            response=_Response(200, {"status": "ready"}),
        )
    assert chain.read_bytes() == original

    monkeypatch.setattr(receipts, "MAX_PUBLIC_RESPONSE_BYTES", 8)
    with pytest.raises(PublicReceiptError, match="sealing bound"):
        seal_public_response(
            tmp_path / "oversized-response.json",
            receipt=first,
            response={"payload": "too large"},
        )


def test_mutation_receipt_converges_only_same_idempotent_response(
    tmp_path: Path,
) -> None:
    chain = tmp_path / "mutation-receipts.jsonl"
    request = {"project_id": "p", "objective": "o"}
    first = append_public_api_receipt(
        chain,
        method="POST",
        route="/v3/sessions",
        request_body=request,
        response=_Response(200, {"session_id": "sess"}),
        idempotency_key="formal-session-create",
    )
    converged = append_public_api_receipt(
        chain,
        method="POST",
        route="/v3/sessions",
        request_body=request,
        response=_Response(200, {"session_id": "sess"}),
        idempotency_key="formal-session-create",
    )

    assert converged == first
    assert len(chain.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(PublicReceiptError, match="exact reconciliation"):
        append_public_api_receipt(
            chain,
            method="POST",
            route="/v3/sessions",
            request_body=request,
            response=_Response(200, {"session_id": "different"}),
            idempotency_key="formal-session-create",
        )


def test_terminal_owner_reconciliation_is_append_only_and_idempotent(
    tmp_path: Path,
) -> None:
    chain = tmp_path / "reconciled.jsonl"
    request = {"project_id": "p", "objective": "o"}
    unknown = append_public_api_receipt(
        chain,
        method="POST",
        route="/v3/sessions",
        request_body=request,
        response=_Response(500, {"error": {"code": "response_lost"}}),
        idempotency_key="session-reconcile",
    )
    terminal = converge_public_api_mutation_receipt(
        chain,
        method="POST",
        route="/v3/sessions",
        request_body=request,
        response_payload={"session_id": "sess_reconciled"},
        status_code=200,
        idempotency_key="session-reconcile",
    )
    repeated = converge_public_api_mutation_receipt(
        chain,
        method="POST",
        route="/v3/sessions",
        request_body=request,
        response_payload={"session_id": "sess_reconciled"},
        status_code=200,
        idempotency_key="session-reconcile",
    )

    assert unknown["effect_certainty"] == "unproven"
    assert terminal["sequence"] == 2
    assert terminal["effect_certainty"] == "terminal_known"
    assert repeated == terminal
    assert len(chain.read_text(encoding="utf-8").splitlines()) == 2
    with pytest.raises(PublicReceiptError, match="differs"):
        converge_public_api_mutation_receipt(
            chain,
            method="POST",
            route="/v3/sessions",
            request_body=request,
            response_payload={"session_id": "sess_drift"},
            status_code=200,
            idempotency_key="session-reconcile",
        )

    response_path = tmp_path / "reconciled-response.json"
    first_envelope = converge_public_response(
        response_path,
        receipt=terminal,
        response={"session_id": "sess_reconciled"},
    )
    second_envelope = converge_public_response(
        response_path,
        receipt=terminal,
        response={"session_id": "sess_reconciled"},
    )
    assert second_envelope == first_envelope
    with pytest.raises(PublicReceiptError, match="semantic digest|differs"):
        converge_public_response(
            response_path,
            receipt=terminal,
            response={"session_id": "sess_drift"},
        )


def test_historical_receipt_chain_is_read_only(tmp_path: Path) -> None:
    chain = tmp_path / "historical-receipts.jsonl"
    current = append_public_api_receipt(
        chain,
        method="GET",
        route="/v3/runtime/health",
        request_body=None,
        response=_Response(200, {"status": "ready"}),
    )
    historical = {
        key: value
        for key, value in current.items()
        if key in receipts.PUBLIC_API_RECEIPT_V2_FIELDS
    }
    historical["schema_id"] = "openzyme_public_api_receipt@2"
    chain.write_bytes(canonical_json_bytes(historical) + b"\n")

    with pytest.raises(PublicReceiptError, match="read-only"):
        require_current_public_receipt_chain(chain)
    with pytest.raises(PublicReceiptError, match="read-only"):
        append_public_api_receipt(
            chain,
            method="GET",
            route="/v3/runtime/health",
            request_body=None,
            response=_Response(200, {"status": "ready"}),
        )
    assert chain.read_bytes() == canonical_json_bytes(historical) + b"\n"
