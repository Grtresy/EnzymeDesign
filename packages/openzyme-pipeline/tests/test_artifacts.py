from __future__ import annotations

from collections.abc import Callable

import pytest

from openzyme_pipeline import artifacts
from openzyme_pipeline.client import PipelineSdkError


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


def test_registered_artifact_ref_uses_closed_registration_projection() -> None:
    digest = f"sha256:{'a' * 64}"

    assert artifacts.registered_artifact_ref(
        {
            "artifact": {
                "artifact_id": "art_registered",
                "metadata": {"sealed_digest": digest},
            },
            "content_digest": digest,
            "validation": {"status": "passed"},
        }
    ) == {
        "artifact_id": "art_registered",
        "content_digest": digest,
    }


def test_registered_artifact_ref_rejects_inconsistent_digest_projection() -> None:
    with pytest.raises(PipelineSdkError, match="inconsistent content digests"):
        artifacts.registered_artifact_ref(
            {
                "artifact": {
                    "artifact_id": "art_registered",
                    "metadata": {"sealed_digest": f"sha256:{'b' * 64}"},
                },
                "content_digest": f"sha256:{'a' * 64}",
            }
        )


def test_provider_file_ref_reads_only_direct_transcript_manifest() -> None:
    digest = f"sha256:{'c' * 64}"
    canonical_file = {
        "artifact_id": "art_ncbi_fasta",
        "content_digest": digest,
        "relative_path": "providers/ncbi/provider_parsed/proteins.fasta",
    }
    response = {
        "result_summary": {
            "transcript_manifest": {"files": [canonical_file]},
            "nested_projection": canonical_file,
        },
        "adapter_result_envelope": {"copied_projection": canonical_file},
    }

    assert artifacts.provider_file_ref(
        response,
        relative_path_suffix="/provider_parsed/proteins.fasta",
    ) == {
        "artifact_id": "art_ncbi_fasta",
        "content_digest": digest,
    }


def test_provider_file_ref_rejects_ambiguous_direct_manifest() -> None:
    digest = f"sha256:{'d' * 64}"
    file_record = {
        "artifact_id": "art_duplicate",
        "content_digest": digest,
        "relative_path": "providers/ncbi/provider_parsed/proteins.fasta",
    }

    with pytest.raises(PipelineSdkError, match="found 2"):
        artifacts.provider_file_ref(
            {
                "result_summary": {
                    "transcript_manifest": {
                        "files": [file_record, dict(file_record)],
                    }
                }
            },
            relative_path_suffix="/provider_parsed/proteins.fasta",
        )


def test_fetched_output_ref_reads_only_direct_fetch_refs() -> None:
    digest = f"sha256:{'e' * 64}"
    direct_ref = {
        "declared_output_path": "bio_tools/mafft/alignment.fasta",
        "registered_artifact_id": "art_alignment",
        "output_digest": digest,
    }
    response = {
        "fetch_refs": [direct_ref],
        "artifacts": [
            {
                "declared_output_path": "bio_tools/mafft/alignment.fasta",
                "registered_artifact_id": "art_alignment",
                "output_digest": digest,
            }
        ],
    }

    assert artifacts.fetched_output_ref(
        response,
        declared_output_path="bio_tools/mafft/alignment.fasta",
    ) == {
        "artifact_id": "art_alignment",
        "content_digest": digest,
    }


def test_fetched_output_ref_rejects_ambiguous_direct_fetch_refs() -> None:
    digest = f"sha256:{'f' * 64}"
    fetch_ref = {
        "declared_output_path": "bio_tools/hmmbuild/model.hmm",
        "registered_artifact_id": "art_hmm",
        "output_digest": digest,
    }

    with pytest.raises(PipelineSdkError, match="found 2"):
        artifacts.fetched_output_ref(
            {"fetch_refs": [fetch_ref, dict(fetch_ref)]},
            declared_output_path="bio_tools/hmmbuild/model.hmm",
        )


@pytest.mark.parametrize(
    "helper, payload, kwargs",
    [
        (
            artifacts.registered_artifact_ref,
            {
                "artifact": {"artifact_id": "art_bad"},
                "content_digest": "not-a-digest",
            },
            {},
        ),
        (
            artifacts.provider_file_ref,
            {
                "result_summary": {
                    "transcript_manifest": {
                        "files": [
                            {
                                "artifact_id": "art_bad",
                                "content_digest": "not-a-digest",
                                "relative_path": "p/provider_parsed/proteins.fasta",
                            }
                        ]
                    }
                }
            },
            {"relative_path_suffix": "/provider_parsed/proteins.fasta"},
        ),
        (
            artifacts.fetched_output_ref,
            {
                "fetch_refs": [
                    {
                        "declared_output_path": "bio_tools/mafft/alignment.fasta",
                        "registered_artifact_id": "art_bad",
                        "output_digest": "not-a-digest",
                    }
                ]
            },
            {"declared_output_path": "bio_tools/mafft/alignment.fasta"},
        ),
    ],
)
def test_artifact_ref_helpers_reject_noncanonical_digests(
    helper: Callable[..., dict[str, str]],
    payload: dict[str, object],
    kwargs: dict[str, str],
) -> None:
    with pytest.raises(PipelineSdkError, match="canonical sha256 digest"):
        helper(payload, **kwargs)
