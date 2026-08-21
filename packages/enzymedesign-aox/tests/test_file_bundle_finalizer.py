from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from enzymedesign_aox import AOX_CANDIDATE_CALCULATION_ID
from enzymedesign_aox import AOX_FINALIZATION_CALCULATION_ID
from enzymedesign_aox import AOX_SCIENTIFIC_FILE_ROLES
from enzymedesign_aox import AoxFileBundleFinalizationError
from enzymedesign_aox import AoxFileBundleFinalizer
from enzymedesign_aox import AoxScientificDeliverableRequestHandler
from enzymedesign_aox import AoxScientificFileContractError
from enzymedesign_aox import file_bundle_finalizer as finalizer_module


DIGEST = "sha256:" + "a" * 64


def test_aox_request_handler_rejects_artifact_era_fields_before_ports() -> None:
    handler = AoxScientificDeliverableRequestHandler(
        calculation_receipts=SimpleNamespace()  # type: ignore[arg-type]
    )

    with pytest.raises(
        RuntimeError,
        match="AOX scientific finalization request fields are closed",
    ):
        handler.finalize_request(
            request={
                "schema_version": "aox_scientific_file_finalize_request@1",
                "publication_id": "publication-1",
                "attempt_id": "attempt-1",
                "selection_id": "selection-1",
                "execution_fencing_token": 1,
                "producer_adoption_ids_by_role": {},
                "calculation_receipts": [],
                "artifact_ids": ["artifact-era"],
            },
            actor_ref="agent-1",
            published_files=SimpleNamespace(),  # type: ignore[arg-type]
            scientific_finalization=SimpleNamespace(),  # type: ignore[arg-type]
        )


def _aox_files(*, empty: bool = False) -> dict[str, bytes]:
    reason = "no_candidates_after_exact_filters"
    empty_file = json.dumps(
        {
            "schema_id": "aox_conditional_empty_file@1",
            "calculation_id": "aox_empty_fixture@1",
            "empty_result_reason": reason,
            "source_output_digest": DIGEST,
            "source_receipt_digest": DIGEST,
        },
        sort_keys=True,
    ).encode()
    files: dict[str, bytes] = {}
    for entry in AOX_SCIENTIFIC_FILE_ROLES:
        if entry.format_contract_id in {"fasta@1", "aligned_fasta@1"}:
            files[entry.path] = empty_file if empty else b">sequence_1\nACDE\n"
        elif entry.format_contract_id == "csv@1":
            files[entry.path] = b"record_id\n"
        elif entry.format_contract_id == "hmmer3@1":
            files[entry.path] = b"HMMER3/f [fixture]\n//\n"
        elif entry.format_contract_id == "aox_execution_summary@1":
            payload: dict[str, object] = {"candidate_count": 0 if empty else 1}
            if empty:
                payload["empty_result"] = {
                    "schema_id": "aox_conditional_empty_result@1",
                    "reason": reason,
                    "receipt_digest": DIGEST,
                }
            files[entry.path] = json.dumps(payload, sort_keys=True).encode()
        else:
            files[entry.path] = b"{}\n"
    return files


class _PublishedFiles:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.reads: list[tuple[str, str]] = []

    def read_bytes(self, *, publication_id: str, path: str) -> bytes:
        self.reads.append((publication_id, path))
        return self.files[path]


class _Record:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _ScientificFinalization:
    def __init__(self) -> None:
        self.command: object | None = None

    def finalize(self, command: object) -> object:
        self.command = command
        requirements = command.requirements  # type: ignore[attr-defined]
        return SimpleNamespace(
            bundle=_Record({"bundle_id": "bundle_1"}),
            receipt=_Record({"receipt_id": "receipt_1"}),
            refs=tuple(
                _Record({"scientific_role": item.scientific_role})
                for item in requirements
            ),
        )


class _ReceiptValidator:
    def __init__(self) -> None:
        self.validated: list[dict[str, object]] = []

    def validate_receipt(self, receipt: object) -> object:
        normalized = dict(receipt)  # type: ignore[arg-type]
        self.validated.append(normalized)
        return normalized


def _calculation_receipts() -> list[dict[str, object]]:
    return [
        {"calculation_id": AOX_CANDIDATE_CALCULATION_ID},
        {"calculation_id": AOX_FINALIZATION_CALCULATION_ID},
    ]


def _adoptions() -> dict[str, str]:
    return {
        entry.role: f"adoption_{index}"
        for index, entry in enumerate(AOX_SCIENTIFIC_FILE_ROLES)
    }


def _finalizer(
    files: dict[str, bytes],
) -> tuple[
    AoxFileBundleFinalizer,
    _PublishedFiles,
    _ScientificFinalization,
    _ReceiptValidator,
]:
    published = _PublishedFiles(files)
    scientific = _ScientificFinalization()
    receipts = _ReceiptValidator()
    return (
        AoxFileBundleFinalizer(published, scientific, receipts),
        published,
        scientific,
        receipts,
    )


def test_aox_finalizer_validates_exact_17_role_published_bundle() -> None:
    finalizer, published, scientific, receipts = _finalizer(_aox_files())
    result = finalizer.finalize(
        publication_id="publication_1",
        attempt_id="attempt_1",
        selection_id="selection_1",
        actor_ref="agent:scientist",
        execution_fencing_token=9,
        producer_adoption_ids_by_role=_adoptions(),
        calculation_receipts=_calculation_receipts(),
    )

    command = scientific.command
    assert command is not None
    assert len(command.requirements) == 17  # type: ignore[attr-defined]
    assert len(result["deliverables"]) == 17
    assert result["scientific_validation"]["role_count"] == 17  # type: ignore[index]
    assert result["task_transition_performed"] is False
    assert result["attempt_transition_performed"] is False
    assert result["campaign_decision_performed"] is False
    assert {path for _, path in published.reads} == set(_aox_files())
    assert {publication_id for publication_id, _ in published.reads} == {
        "publication_1"
    }
    assert {item["calculation_id"] for item in receipts.validated} == {
        AOX_CANDIDATE_CALCULATION_ID,
        AOX_FINALIZATION_CALCULATION_ID,
    }


def test_aox_finalizer_accepts_contract_valid_empty_result() -> None:
    finalizer, _, _, _ = _finalizer(_aox_files(empty=True))
    result = finalizer.finalize(
        publication_id="publication_1",
        attempt_id="attempt_1",
        selection_id="selection_1",
        actor_ref="agent:scientist",
        execution_fencing_token=9,
        producer_adoption_ids_by_role=_adoptions(),
        calculation_receipts=_calculation_receipts(),
    )

    validation = result["scientific_validation"]
    assert validation["candidate_count"] == 0  # type: ignore[index]
    assert len(validation["typed_empty_paths"]) > 0  # type: ignore[index]


def test_aox_finalizer_rejects_incomplete_roles_receipts_and_malformed_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finalizer, _, _, _ = _finalizer(_aox_files())
    missing = _adoptions()
    missing.pop(next(iter(missing)))
    with pytest.raises(AoxFileBundleFinalizationError, match="exact 17 roles"):
        finalizer.finalize(
            publication_id="publication_1",
            attempt_id="attempt_1",
            selection_id="selection_1",
            actor_ref="agent:scientist",
            execution_fencing_token=9,
            producer_adoption_ids_by_role=missing,
            calculation_receipts=_calculation_receipts(),
        )

    roles = finalizer_module.AOX_SCIENTIFIC_FILE_ROLES
    monkeypatch.setattr(
        finalizer_module,
        "AOX_SCIENTIFIC_FILE_ROLES",
        roles[:-1] + (roles[0],),
    )
    with pytest.raises(AoxScientificFileContractError, match="exact ordered 17-role"):
        finalizer.finalize(
            publication_id="publication_1",
            attempt_id="attempt_1",
            selection_id="selection_1",
            actor_ref="agent:scientist",
            execution_fencing_token=9,
            producer_adoption_ids_by_role=_adoptions(),
            calculation_receipts=_calculation_receipts(),
        )
    monkeypatch.setattr(finalizer_module, "AOX_SCIENTIFIC_FILE_ROLES", roles)

    malformed = _aox_files()
    malformed[roles[0].path] = b"not-valid-for-role\n"
    malformed_finalizer, _, _, _ = _finalizer(malformed)
    with pytest.raises(AoxScientificFileContractError):
        malformed_finalizer.finalize(
            publication_id="publication_1",
            attempt_id="attempt_1",
            selection_id="selection_1",
            actor_ref="agent:scientist",
            execution_fencing_token=9,
            producer_adoption_ids_by_role=_adoptions(),
            calculation_receipts=_calculation_receipts(),
        )

    with pytest.raises(AoxFileBundleFinalizationError, match="incomplete"):
        finalizer.finalize(
            publication_id="publication_1",
            attempt_id="attempt_1",
            selection_id="selection_1",
            actor_ref="agent:scientist",
            execution_fencing_token=9,
            producer_adoption_ids_by_role=_adoptions(),
            calculation_receipts=[{"calculation_id": AOX_CANDIDATE_CALCULATION_ID}],
        )
