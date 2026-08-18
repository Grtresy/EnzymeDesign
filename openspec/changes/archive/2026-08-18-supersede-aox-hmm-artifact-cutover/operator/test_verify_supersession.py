from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest


MODULE_PATH = Path(__file__).with_name("verify_supersession.py")
SPEC = importlib.util.spec_from_file_location("verify_supersession", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def _operator_copy(tmp_path: Path) -> Path:
    operator_dir = tmp_path / "operator"
    operator_dir.mkdir()
    for name in (
        "scope_gate",
        "inventory",
        "manifest",
        "operator_index",
        "negative_checklist",
        "governance_receipt",
    ):
        filename, _ = VERIFIER.DOCUMENTS[name]
        shutil.copy2(MODULE_PATH.with_name(filename), operator_dir / filename)
    return operator_dir


def _rewrite_document(
    operator_dir: Path,
    name: str,
    mutate: Callable[[dict[str, Any]], None],
    *,
    close_digest: bool = True,
) -> None:
    filename, digest_field = VERIFIER.DOCUMENTS[name]
    path = operator_dir / filename
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    if close_digest:
        preimage = {
            key: value for key, value in document.items() if key != digest_field
        }
        document[digest_field] = VERIFIER.digest_value(preimage)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _verify_from(operator_dir: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(VERIFIER, "OPERATOR_DIR", operator_dir)
    return VERIFIER.verify_all(require_acceptance=False, verify_sources=False)


def test_complete_governance_manifest_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _verify_from(_operator_copy(tmp_path), monkeypatch)
    assert result["status"] == "passed"
    assert result["external_effects"] == 0


def test_missing_governance_receipt_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    (operator_dir / "c0-governance-gate-receipt.json").unlink()
    with pytest.raises(ValueError, match="required operator document is missing"):
        _verify_from(operator_dir, monkeypatch)


def test_missing_legacy_receipt_identity_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    _rewrite_document(
        operator_dir,
        "inventory",
        lambda document: document["identity_sets"]["receipts"].pop(),
    )
    with pytest.raises(ValueError, match="receipts inventory count"):
        _verify_from(operator_dir, monkeypatch)


def test_legacy_task_omission_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    _rewrite_document(
        operator_dir,
        "inventory",
        lambda document: document["legacy_tasks"].pop(2),
    )
    with pytest.raises(ValueError, match="legacy task inventory"):
        _verify_from(operator_dir, monkeypatch)


def test_canonical_digest_tamper_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    _rewrite_document(
        operator_dir,
        "inventory",
        lambda document: document["c001"].update(
            {"attempt_status": "closed_fabricated"}
        ),
        close_digest=False,
    )
    with pytest.raises(ValueError, match="canonical digest does not match"):
        _verify_from(operator_dir, monkeypatch)


def test_legacy_authority_reuse_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    _rewrite_document(
        operator_dir,
        "manifest",
        lambda document: document["legacy_identity_disposition"]["authority"].update(
            {"successor_admission_input": True}
        ),
    )
    with pytest.raises(ValueError, match="authority disposition permits forbidden reuse"):
        _verify_from(operator_dir, monkeypatch)


def test_byte_equivalence_cannot_be_adopted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    _rewrite_document(
        operator_dir,
        "manifest",
        lambda document: document["historical_migration"].update(
            {"may_create_published_revision": True}
        ),
    )
    with pytest.raises(ValueError, match="migration could create current truth"):
        _verify_from(operator_dir, monkeypatch)


def test_legacy_delta_cannot_sync_to_main_specs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    _rewrite_document(
        operator_dir,
        "manifest",
        lambda document: document.update({"merge_to_main_specs": True}),
    )
    with pytest.raises(ValueError, match="must not enter main specs"):
        _verify_from(operator_dir, monkeypatch)


def test_acceptance_is_required_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    monkeypatch.setattr(VERIFIER, "OPERATOR_DIR", operator_dir)
    with pytest.raises(ValueError, match="acceptance-receipt.json"):
        VERIFIER.verify_all(require_acceptance=True, verify_sources=False)
