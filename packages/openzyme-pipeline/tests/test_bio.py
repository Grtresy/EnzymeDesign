from __future__ import annotations

from typing import Any

import pytest

from openzyme_pipeline import bio


HMM_DIGEST = "sha256:" + "a" * 64
HIT_DIGEST = "sha256:" + "b" * 64


def _capture_controlled_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(bio, "supervised_sandbox_mode", lambda: True)

    def controlled_operation(**kwargs: Any) -> dict[str, str]:
        captured.append(kwargs)
        return {"operation_id": "op_test"}

    monkeypatch.setattr(bio, "controlled_operation", controlled_operation)
    return captured


@pytest.mark.parametrize(
    "output_dir",
    [
        "providers/ncbi",
        "/workspace/output",
        "/workspace/input/providers/ncbi",
        "/workspace/output/../input/ncbi",
        " /workspace/output/providers/ncbi",
        "/workspace/output/providers/ncbi\n",
        "C:\\workspace\\output\\providers\\ncbi",
    ],
)
@pytest.mark.parametrize("method", ["ncbi_fetch_proteins", "uniprot_fetch"])
def test_provider_calls_fail_fast_before_operation_for_invalid_output_dir(
    monkeypatch: pytest.MonkeyPatch,
    output_dir: str,
    method: str,
) -> None:
    captured = _capture_controlled_operation(monkeypatch)

    with pytest.raises(ValueError, match="absolute path under /workspace/output"):
        if method == "ncbi_fetch_proteins":
            bio.ncbi_fetch_proteins(
                accessions=["AAB57849.1"],
                output_dir=output_dir,
            )
        else:
            bio.uniprot_fetch(
                accessions=["P12345"],
                output_dir=output_dir,
            )

    assert captured == []


def test_hmmer_search_fails_fast_before_input_binding_for_invalid_output_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_controlled_operation(monkeypatch)

    with pytest.raises(ValueError, match="absolute path under /workspace/output"):
        bio.hmmer_search(
            hmm_artifact_id="art_hmm_001",
            hmm_artifact_digest=HMM_DIGEST,
            database="refprot",
            output_dir="providers/hmmer",
        )

    assert captured == []


def test_hmmer_search_binds_hmm_artifact_id_and_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_controlled_operation(monkeypatch)

    result = bio.hmmer_search(
        hmm_artifact_id="art_hmm_001",
        hmm_artifact_digest=HMM_DIGEST,
        database="refprot",
        output_dir="/workspace/output/bio/hmmer",
        params={"E": 1e-5},
    )

    assert result == {"operation_id": "op_test"}
    assert len(captured) == 1
    envelope = captured[0]
    assert envelope["params"] == {
        "hmm_artifact_id": "art_hmm_001",
        "hmm_artifact_digest": HMM_DIGEST,
        "database": "refprot",
        "params": {"E": 1e-5},
        "output_dir": "/workspace/output/bio/hmmer",
    }
    assert envelope["input_artifact_ids"] == ["art_hmm_001"]
    assert envelope["input_artifact_digests"] == [HMM_DIGEST]
    assert envelope["stage_refs"] == [
        {"artifact_id": "art_hmm_001", "content_digest": HMM_DIGEST}
    ]


@pytest.mark.parametrize("digest", [None, "", "sha256:bad", "sha256:" + "A" * 64])
def test_hmmer_search_fails_closed_without_canonical_digest(
    monkeypatch: pytest.MonkeyPatch,
    digest: str | None,
) -> None:
    captured = _capture_controlled_operation(monkeypatch)

    with pytest.raises(ValueError, match="content_digest as sha256"):
        bio.hmmer_search(
            hmm_artifact_id="art_hmm_001",
            hmm_artifact_digest=digest,
            database="refprot",
            output_dir="/workspace/output/bio/hmmer",
        )

    assert captured == []


def test_uniprot_fetch_binds_source_hit_artifact_without_rewriting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_controlled_operation(monkeypatch)
    source_hit_artifact = {
        "artifact_id": "art_ebi_hits_001",
        "content_digest": HIT_DIGEST,
    }

    result = bio.uniprot_fetch(
        accessions=["P12345", "Q8XYZ1"],
        output_dir="/workspace/output/bio/uniprot",
        fields=["accession", "sequence"],
        batch_size=50,
        source_sequence_identities={"P12345": {"sequence_digest": HMM_DIGEST}},
        sequence_mismatch_choices={"P12345": "uniprot"},
        source_hit_artifact=source_hit_artifact,
    )

    assert result == {"operation_id": "op_test"}
    assert len(captured) == 1
    envelope = captured[0]
    assert envelope["params"] == {
        "accessions": ["P12345", "Q8XYZ1"],
        "fields": ["accession", "sequence"],
        "batch_size": 50,
        "source_sequence_identities": {"P12345": {"sequence_digest": HMM_DIGEST}},
        "sequence_mismatch_choices": {"P12345": "uniprot"},
        "source_hit_artifact": source_hit_artifact,
        "output_dir": "/workspace/output/bio/uniprot",
    }
    assert envelope["input_artifact_ids"] == ["art_ebi_hits_001"]
    assert envelope["input_artifact_digests"] == [HIT_DIGEST]
    assert envelope["stage_refs"] == [source_hit_artifact]
    assert envelope["resource_estimate"] == {
        "network_io": True,
        "accession_count": 2,
        "estimated_query_batch_count": 1,
        "query_batch_size_cap": 100,
    }


def test_uniprot_real_scale_list_remains_one_controlled_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_controlled_operation(monkeypatch)
    accessions = [f"P{index:05d}" for index in range(37_772)]

    result = bio.uniprot_fetch(
        accessions=accessions,
        output_dir="/workspace/output/bio/uniprot",
        batch_size=100,
    )

    assert result == {"operation_id": "op_test"}
    assert len(captured) == 1
    envelope = captured[0]
    assert envelope["params"]["accessions"] == accessions
    assert envelope["resource_estimate"] == {
        "network_io": True,
        "accession_count": 37_772,
        "estimated_query_batch_count": 378,
        "query_batch_size_cap": 100,
    }


@pytest.mark.parametrize(
    "source_hit_artifact",
    [
        {"artifact_id": "art_ebi_hits_001"},
        {"artifact_id": "art_ebi_hits_001", "content_digest": ""},
        {"artifact_id": "art_ebi_hits_001", "content_digest": "sha256:bad"},
        {"artifact_id": " ", "content_digest": HIT_DIGEST},
        {
            "artifact_id": "art_ebi_hits_001",
            "content_digest": HIT_DIGEST,
            "storage_hint": "must-not-cross-provider-boundary",
        },
    ],
)
def test_uniprot_fetch_fails_closed_for_invalid_source_hit_artifact(
    monkeypatch: pytest.MonkeyPatch,
    source_hit_artifact: dict[str, str],
) -> None:
    captured = _capture_controlled_operation(monkeypatch)

    with pytest.raises(ValueError, match="provider input refs require"):
        bio.uniprot_fetch(
            accessions=["P12345"],
            output_dir="/workspace/output/bio/uniprot",
            source_hit_artifact=source_hit_artifact,
        )

    assert captured == []
