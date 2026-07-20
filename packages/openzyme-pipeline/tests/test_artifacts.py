from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import Path

import pytest

from openzyme_domain import ArtifactKind
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
            "derivation_contract_id": "aox_sequence_length_join@2",
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
                    "derivation_contract_id": "aox_sequence_length_join@2",
                },
            },
        )
    ]


def test_register_spills_large_metadata_to_canonical_digest_bound_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def _call(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        return {"artifact": {"artifact_id": "artifact_large"}}

    sidecar_root = tmp_path / "work" / ".openzyme" / "artifact-metadata"
    monkeypatch.setattr(
        artifacts,
        "ARTIFACT_REGISTRATION_METADATA_WORK_ROOT",
        tmp_path / "work",
    )
    monkeypatch.setattr(
        artifacts,
        "ARTIFACT_REGISTRATION_METADATA_INLINE_MAX_BYTES",
        128,
    )
    monkeypatch.setattr(
        artifacts,
        "ARTIFACT_REGISTRATION_METADATA_SIDECAR_MAX_BYTES",
        16 * 1024,
    )
    monkeypatch.setattr(artifacts, "call", _call)
    metadata = {
        "contract_id": "aox_sequence_length_join@2",
        "identity_mappings": [
            {"requested_accession": f"A{index:05d}", "padding": "x" * 64}
            for index in range(32)
        ],
    }

    artifacts.register(
        "/workspace/output/aox_hmm/hits_len650_700_200.csv",
        kind="result",
        format="csv",
        metadata=metadata,
    )

    assert len(calls) == 1
    method, params = calls[0]
    assert method == "artifacts.register"
    assert "metadata" not in params
    descriptor = params["metadata_sidecar"]
    assert isinstance(descriptor, dict)
    assert descriptor["schema_id"] == "artifact_registration_metadata_sidecar@1"
    assert descriptor["path"] == (
        "/workspace/work/.openzyme/artifact-metadata/"
        f"{str(descriptor['content_digest'])[7:]}.json"
    )
    path = sidecar_root / f"{str(descriptor['content_digest'])[7:]}.json"
    expected = json.dumps(
        metadata,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert path.read_bytes() == expected
    assert descriptor["size_bytes"] == len(expected)
    assert descriptor["content_digest"] == (
        f"sha256:{hashlib.sha256(expected).hexdigest()}"
    )
    assert path.stat().st_mode & 0o777 == 0o600


def test_register_sidecar_is_no_replace_on_digest_path_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def _call(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        return {"artifact": {"artifact_id": "artifact_large"}}

    monkeypatch.setattr(
        artifacts,
        "ARTIFACT_REGISTRATION_METADATA_WORK_ROOT",
        tmp_path / "work",
    )
    monkeypatch.setattr(
        artifacts,
        "ARTIFACT_REGISTRATION_METADATA_INLINE_MAX_BYTES",
        8,
    )
    monkeypatch.setattr(artifacts, "call", _call)
    metadata = {"identity_mappings": ["A", "B", "C"]}

    artifacts.register(
        "/workspace/output/result.csv",
        metadata=metadata,
    )
    descriptor = calls[0][1]["metadata_sidecar"]
    assert isinstance(descriptor, dict)
    path = (
        artifacts.ARTIFACT_REGISTRATION_METADATA_WORK_ROOT
        / ".openzyme"
        / "artifact-metadata"
        / f"{str(descriptor['content_digest'])[7:]}.json"
    )
    path.write_text("tampered", encoding="utf-8")

    with pytest.raises(PipelineSdkError) as error:
        artifacts.register(
            "/workspace/output/result.csv",
            metadata=metadata,
        )

    assert error.value.error_code == (
        "artifact_registration_metadata_sidecar_write_failed"
    )
    assert len(calls) == 1
    assert path.read_text(encoding="utf-8") == "tampered"


def test_register_rejects_metadata_above_sidecar_limit_before_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        artifacts,
        "ARTIFACT_REGISTRATION_METADATA_WORK_ROOT",
        tmp_path / "work",
    )
    monkeypatch.setattr(
        artifacts,
        "ARTIFACT_REGISTRATION_METADATA_INLINE_MAX_BYTES",
        8,
    )
    monkeypatch.setattr(
        artifacts,
        "ARTIFACT_REGISTRATION_METADATA_SIDECAR_MAX_BYTES",
        32,
    )
    monkeypatch.setattr(
        artifacts,
        "call",
        lambda method, params: calls.append((method, params)),
    )

    with pytest.raises(PipelineSdkError) as error:
        artifacts.register(
            "/workspace/output/result.csv",
            metadata={"padding": "x" * 128},
        )

    assert error.value.error_code == "artifact_registration_metadata_too_large"
    expected_size = len(
        json.dumps(
            {"padding": "x" * 128},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )
    assert error.value.details == {"max_bytes": 32, "size_bytes": expected_size}
    assert calls == []


@pytest.mark.parametrize("reserved_field", ["content_digest", "sealed_digest", "tree_digest"])
def test_register_rejects_host_owned_digest_metadata_before_control_call(
    reserved_field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        artifacts,
        "call",
        lambda method, params: calls.append((method, params)),
    )

    with pytest.raises(PipelineSdkError) as error:
        artifacts.register(
            "/workspace/output/result.csv",
            metadata={reserved_field: f"sha256:{'a' * 64}"},
        )

    assert error.value.error_code == "artifact_registration_metadata_reserved"
    assert error.value.stage == "artifacts.request_validation"
    assert error.value.retryable is False
    assert error.value.details == {"reserved_fields": [reserved_field]}
    assert calls == []


def test_register_many_reuses_one_large_metadata_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def _call(method: str, params: dict[str, object]) -> list[dict[str, object]]:
        calls.append((method, params))
        return []

    monkeypatch.setattr(
        artifacts,
        "ARTIFACT_REGISTRATION_METADATA_WORK_ROOT",
        tmp_path / "work",
    )
    monkeypatch.setattr(
        artifacts,
        "ARTIFACT_REGISTRATION_METADATA_INLINE_MAX_BYTES",
        8,
    )
    monkeypatch.setattr(artifacts, "call", _call)

    artifacts.register_many(
        ["/workspace/output/one.csv", "/workspace/output/two.csv"],
        metadata={"identity_mappings": ["A", "B", "C"]},
    )

    assert len(calls) == 1
    items = calls[0][1]["items"]
    assert isinstance(items, list)
    assert len(items) == 2
    first_sidecar = items[0]["metadata_sidecar"]
    assert first_sidecar == items[1]["metadata_sidecar"]


def test_register_many_rejects_oversized_batch_before_control_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        artifacts,
        "call",
        lambda method, params: calls.append((method, params)),
    )

    with pytest.raises(PipelineSdkError) as error:
        artifacts.register_many(
            [
                f"/workspace/output/result-{index}.csv"
                for index in range(artifacts.ARTIFACT_REGISTER_MANY_MAX_ITEMS + 1)
            ],
        )

    assert error.value.error_code == "artifact_register_many_too_many_items"
    assert calls == []


def test_register_rejects_invalid_artifact_kind_before_control_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def _call(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        return {"artifact": {"artifact_id": "artifact_unexpected"}}

    monkeypatch.setattr(artifacts, "call", _call)

    with pytest.raises(PipelineSdkError) as error:
        artifacts.register(
            "/workspace/output/aox_hmm/AOX_ref.hmm",
            kind="model",
        )

    assert error.value.error_code == "artifact_kind_invalid"
    assert error.value.stage == "artifacts.request_validation"
    assert error.value.retryable is False
    assert error.value.details == {
        "allowed_values": [
            "code",
            "log",
            "sequence",
            "structure",
            "report",
            "research_dossier",
            "result",
            "cache",
            "other",
        ]
    }
    assert error.value.hint == (
        "Use exactly one of: code, log, sequence, structure, report, "
        "research_dossier, result, cache, other."
    )
    assert calls == []


def test_register_many_rejects_invalid_artifact_kind_before_control_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def _call(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        return {"artifacts": []}

    monkeypatch.setattr(artifacts, "call", _call)

    with pytest.raises(PipelineSdkError) as error:
        artifacts.register_many(
            ["/workspace/output/aox_hmm/AOX_ref.hmm"],
            kind="model",
        )

    assert error.value.error_code == "artifact_kind_invalid"
    assert error.value.retryable is False
    assert calls == []


def test_dependency_free_artifact_kind_allowlist_matches_domain_wire_values() -> None:
    assert artifacts._ARTIFACT_KIND_VALUES == tuple(item.value for item in ArtifactKind)


def _closed_registration_response(content_digest: str) -> dict[str, object]:
    return {
        "schema_id": "artifact_registration_response@2",
        "artifact": {
            "artifact_id": "art_registered",
            "metadata": {
                "schema_id": "artifact_registration_metadata_summary@1",
                "projection": "bounded_registration_summary",
                "metadata_digest": f"sha256:{'d' * 64}",
                "metadata_size_bytes": 128,
                "metadata_field_count": 4,
                "content_digest": content_digest,
                "sealed_digest": content_digest,
                "tree_digest": None,
            },
        },
        "content_digest": content_digest,
        "tree_digest": None,
        "validation": {
            "schema_id": "artifact_registration_validation_summary@1",
            "projection": "bounded_registration_summary",
            "status": "passed",
            "format": "csv",
            "validation_profile": None,
            "empty_result_reason": None,
            "derivation_contract_id": None,
            "required_columns_count": 0,
            "required_columns_digest": f"sha256:{'f' * 64}",
            "validation_digest": f"sha256:{'e' * 64}",
            "validation_size_bytes": 64,
            "required_columns": [],
        },
        "reused": False,
    }


def test_registered_artifact_ref_uses_closed_registration_projection() -> None:
    digest = f"sha256:{'a' * 64}"

    assert artifacts.registered_artifact_ref(_closed_registration_response(digest)) == {
        "artifact_id": "art_registered",
        "content_digest": digest,
    }


def test_registered_artifact_ref_rejects_extra_artifact_context_fields() -> None:
    digest = f"sha256:{'a' * 64}"
    response = _closed_registration_response(digest)
    artifact = response["artifact"]
    assert isinstance(artifact, dict)
    artifact["session_id"] = "sess_caller_controlled"

    with pytest.raises(PipelineSdkError) as error:
        artifacts.registered_artifact_ref(response)

    assert error.value.error_code == "artifact_registration_projection_invalid"


def test_registered_artifact_ref_rejects_oversized_artifact_identity() -> None:
    digest = f"sha256:{'a' * 64}"
    response = _closed_registration_response(digest)
    artifact = response["artifact"]
    assert isinstance(artifact, dict)
    artifact["artifact_id"] = "a" * 257

    with pytest.raises(PipelineSdkError) as error:
        artifacts.registered_artifact_ref(response)

    assert error.value.error_code == "artifact_registration_projection_invalid"


@pytest.mark.parametrize("metadata_digest_field", ["content_digest", "sealed_digest"])
def test_registered_artifact_ref_rejects_inconsistent_digest_projection(
    metadata_digest_field: str,
) -> None:
    response = _closed_registration_response(f"sha256:{'a' * 64}")
    artifact = response["artifact"]
    assert isinstance(artifact, dict)
    metadata = artifact["metadata"]
    assert isinstance(metadata, dict)
    metadata[metadata_digest_field] = f"sha256:{'b' * 64}"

    with pytest.raises(PipelineSdkError, match="inconsistent content digests"):
        artifacts.registered_artifact_ref(response)


@pytest.mark.parametrize("metadata_digest_field", ["content_digest", "sealed_digest"])
def test_registered_artifact_ref_rejects_missing_file_digest_projection(
    metadata_digest_field: str,
) -> None:
    response = _closed_registration_response(f"sha256:{'a' * 64}")
    artifact = response["artifact"]
    assert isinstance(artifact, dict)
    metadata = artifact["metadata"]
    assert isinstance(metadata, dict)
    metadata[metadata_digest_field] = None

    with pytest.raises(PipelineSdkError, match="inconsistent content digests"):
        artifacts.registered_artifact_ref(response)


@pytest.mark.parametrize("tree_digest_location", ["response", "metadata"])
def test_registered_artifact_ref_rejects_tree_digest_for_file_ref(
    tree_digest_location: str,
) -> None:
    response = _closed_registration_response(f"sha256:{'a' * 64}")
    if tree_digest_location == "response":
        response["tree_digest"] = f"sha256:{'b' * 64}"
    else:
        artifact = response["artifact"]
        assert isinstance(artifact, dict)
        metadata = artifact["metadata"]
        assert isinstance(metadata, dict)
        metadata["tree_digest"] = f"sha256:{'b' * 64}"

    with pytest.raises(PipelineSdkError, match="must not carry a tree digest"):
        artifacts.registered_artifact_ref(response)


@pytest.mark.parametrize(
    "response",
    [
        {"artifact": {"artifact_id": "legacy"}},
        {
            "schema_id": "pipeline_provisional_registration_response@1",
            "canonical": False,
            "artifact_id": "pipeline:1:result.csv",
        },
    ],
)
def test_registered_artifact_ref_rejects_noncanonical_response_schemas(
    response: dict[str, object],
) -> None:
    with pytest.raises(PipelineSdkError) as error:
        artifacts.registered_artifact_ref(response)

    assert error.value.error_code == "artifact_registration_projection_invalid"


def test_registered_artifact_ref_rejects_already_selected_canonical_ref() -> None:
    canonical_ref = {
        "artifact_id": "art_provider_fasta",
        "content_digest": f"sha256:{'c' * 64}",
    }

    with pytest.raises(PipelineSdkError) as error:
        artifacts.registered_artifact_ref(canonical_ref)

    assert error.value.error_code == "artifact_ref_already_canonical"
    assert error.value.stage == "artifacts.response_selection"
    assert error.value.retryable is False
    assert "already a canonical artifact ref" in str(error.value)
    assert "provider_file_ref and fetched_output_ref are terminal selectors" in str(
        error.value.hint
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
            _closed_registration_response("not-a-digest"),
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
