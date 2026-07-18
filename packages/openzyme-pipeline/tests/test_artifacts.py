from __future__ import annotations

import pytest

from openzyme_pipeline import artifacts


def test_register_forwards_typed_validation_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def _call(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        return {"artifact": {"artifact_id": "artifact_empty"}}

    monkeypatch.setattr(artifacts, "call", _call)

    result = artifacts.register(
        "/workspace/output/target.fasta",
        kind="sequence",
        format="fasta",
        validation_profile="fasta_zero_records@1",
        metadata={
            "empty_result_reason": "no_candidates_after_length_filter",
            "derivation_contract_id": "aox_sequence_length_join@1",
        },
    )

    assert result["artifact"]["artifact_id"] == "artifact_empty"
    assert calls == [
        (
            "artifacts.register",
            {
                "path": "/workspace/output/target.fasta",
                "kind": "sequence",
                "format": "fasta",
                "validation_profile": "fasta_zero_records@1",
                "metadata": {
                    "empty_result_reason": "no_candidates_after_length_filter",
                    "derivation_contract_id": "aox_sequence_length_join@1",
                },
            },
        )
    ]
