from __future__ import annotations

from typing import Any

import pytest

from openzyme_pipeline import bio_tools
from openzyme_pipeline.client import PipelineSdkError
from openzyme_pipeline.hpc import HpcWorkspace


ARTIFACT_DIGEST = "sha256:" + "a" * 64


def _workspace() -> HpcWorkspace:
    return HpcWorkspace(
        hpc_workspace_id="hpcws_test",
        label="aox_hmm",
        normalized_label="aox_hmm",
    )


def _stage_ref(*, artifact_id: str = "art_sequences") -> dict[str, str]:
    return {
        "kind": "hpc_stage_ref",
        "stage_ref_id": "stage_test",
        "hpc_workspace_id": "hpcws_test",
        "artifact_id": artifact_id,
        "artifact_digest": ARTIFACT_DIGEST,
        "workspace_relative_path": "input/sequences.fasta",
        "source": "artifact_catalog",
        "sandbox_workspace_id": "sw_test",
    }


def _capture_controlled_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(bio_tools, "supervised_sandbox_mode", lambda: True)

    def controlled_operation(**kwargs: Any) -> dict[str, str]:
        captured.append(kwargs)
        return {"operation_id": "op_test"}

    monkeypatch.setattr(bio_tools, "controlled_operation", controlled_operation)
    return captured


def test_mafft_binds_exact_hpc_stage_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_controlled_operation(monkeypatch)
    stage_ref = _stage_ref()

    result = bio_tools.mafft(
        input_fasta=stage_ref,
        placement=_workspace(),
        expected_outputs=[
            {
                "path": "bio_tools/mafft/alignment.fasta",
                "kind": "sequence",
                "format": "fasta",
            }
        ],
    )

    assert result == {"operation_id": "op_test"}
    assert len(captured) == 1
    envelope = captured[0]
    assert envelope["stage_refs"] == [stage_ref]
    assert envelope["input_artifact_ids"] == ["art_sequences"]
    assert envelope["input_artifact_digests"] == [ARTIFACT_DIGEST]


def test_mafft_rejects_handwritten_artifact_ref_before_host_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_controlled_operation(monkeypatch)
    handwritten_ref = {
        "artifact_id": "art_sequences",
        "artifact_digest": ARTIFACT_DIGEST,
        "workspace_path": "aox_hmm/AOX_ref21.fasta",
    }

    with pytest.raises(PipelineSdkError) as exc_info:
        bio_tools.mafft(
            input_fasta=handwritten_ref,
            placement=_workspace(),
            expected_outputs=[
                {"path": "bio_tools/mafft/alignment.fasta", "format": "fasta"}
            ],
        )

    error = exc_info.value
    assert error.error_code == "hpc_stage_ref_required"
    assert error.stage == "bio_tools.input_validation"
    assert error.retryable is False
    assert "exact object returned by ws.stage_artifact(...)" in error.message
    assert "do not hand-write" in error.message
    assert "error_code=hpc_stage_ref_required" in str(error)
    assert "ws.stage_artifact(...)" in str(error)
    assert error.hint is not None
    assert "pass staged directly to bio_tools.mafft" in error.hint
    assert error.details == {
        "function_name": "mafft",
        "input_index": 0,
        "expected_kind": "hpc_stage_ref",
        "missing_fields": ["kind", "stage_ref_id", "hpc_workspace_id"],
    }
    assert captured == []


def test_hmmalign_identifies_invalid_second_hpc_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_controlled_operation(monkeypatch)

    with pytest.raises(PipelineSdkError) as exc_info:
        bio_tools.hmmalign(
            hmm=_stage_ref(artifact_id="art_hmm"),
            fasta={"artifact_id": "art_fasta", "artifact_digest": ARTIFACT_DIGEST},
            placement=_workspace(),
            expected_outputs=[
                {"path": "bio_tools/hmmalign/aligned.fasta", "format": "fasta"}
            ],
        )

    assert exc_info.value.error_code == "hpc_stage_ref_required"
    assert exc_info.value.details["function_name"] == "hmmalign"
    assert exc_info.value.details["input_index"] == 1
    assert captured == []
