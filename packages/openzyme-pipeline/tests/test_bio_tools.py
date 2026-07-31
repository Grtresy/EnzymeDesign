from __future__ import annotations

from typing import Any

import pytest

from openzyme_pipeline import bio_tools
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


def test_mafft_forwards_handwritten_artifact_ref_for_host_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_controlled_operation(monkeypatch)
    handwritten_ref = {
        "artifact_id": "art_sequences",
        "artifact_digest": ARTIFACT_DIGEST,
        "workspace_path": "aox_hmm/AOX_ref21.fasta",
    }

    result = bio_tools.mafft(
        input_fasta=handwritten_ref,
        placement=_workspace(),
        expected_outputs=[
            {"path": "bio_tools/mafft/alignment.fasta", "format": "fasta"}
        ],
    )

    assert result == {"operation_id": "op_test"}
    assert len(captured) == 1
    assert captured[0]["stage_refs"] == [handwritten_ref]
    assert captured[0]["input_artifact_ids"] == ["art_sequences"]
    assert captured[0]["input_artifact_digests"] == [ARTIFACT_DIGEST]


def test_hmmalign_forwards_each_input_for_single_host_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_controlled_operation(monkeypatch)
    hmm = _stage_ref(artifact_id="art_hmm")
    fasta = {"artifact_id": "art_fasta", "artifact_digest": ARTIFACT_DIGEST}

    result = bio_tools.hmmalign(
        hmm=hmm,
        fasta=fasta,
        placement=_workspace(),
        expected_outputs=[
            {"path": "bio_tools/hmmalign/aligned.fasta", "format": "fasta"}
        ],
    )

    assert result == {"operation_id": "op_test"}
    assert len(captured) == 1
    assert captured[0]["stage_refs"] == [hmm, fasta]
    assert captured[0]["input_artifact_ids"] == ["art_hmm", "art_fasta"]
    assert captured[0]["input_artifact_digests"] == [
        ARTIFACT_DIGEST,
        ARTIFACT_DIGEST,
    ]
