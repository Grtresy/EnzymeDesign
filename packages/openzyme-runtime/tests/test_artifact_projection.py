from __future__ import annotations

import json
from typing import Any

from openzyme_runtime import PRIVATE_ARTIFACT_KEYS
from openzyme_runtime import project_artifact_list_item_for_agent
from openzyme_runtime import serialize_artifact_projection


class _Artifact:
    def __init__(
        self,
        metadata: Any,
        *,
        description: str | None = None,
    ) -> None:
        self.metadata = metadata
        self.description = description

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "art_large_metadata",
            "session_id": "sess_001",
            "kind": "result",
            "storage_uri": "/tmp/private/result.json",
            "relative_path": "results/result.json",
            "description": self.description,
            "metadata": self.metadata,
        }


def test_artifact_list_projection_is_bounded_and_deterministic() -> None:
    accessions = [f"P{index:06d}" for index in range(37_722)]
    page_digests = [f"sha256:{index:064x}" for index in range(686)]
    contract = {
        "adapter_id": "uniprot_fetch",
        "contract_digest": "sha256:" + "a" * 64,
        "contract_id": "uniprot_fetch@1",
    }
    first_metadata = {
        "raw_page_digests": page_digests,
        "accessions": accessions,
        "provider_contract": contract,
        "accession_count": len(accessions),
        "raw_page_count": len(page_digests),
        "schema_id": "provider_raw_http_response_set@1",
    }
    second_metadata = dict(reversed(list(first_metadata.items())))

    first = project_artifact_list_item_for_agent(_Artifact(first_metadata))
    second = project_artifact_list_item_for_agent(_Artifact(second_metadata))

    assert first == second
    assert first["metadata"] == {
        "accession_count": 37_722,
        "provider_contract": contract,
        "raw_page_count": 686,
        "schema_id": "provider_raw_http_response_set@1",
    }
    summary = first["metadata_summary"]
    assert summary["schema_id"] == "artifact_list_metadata_summary@1"
    assert summary["projected_json_chars"] <= 4_096
    assert len(serialize_artifact_projection(summary)) <= 4_096
    assert summary["omitted_field_count"] == 2
    assert summary["omitted_fields_truncated"] is False
    omitted = {item["path"]: item for item in summary["omitted_fields"]}
    assert omitted["artifact.metadata.accessions"]["item_count"] == 37_722
    assert omitted["artifact.metadata.raw_page_digests"]["item_count"] == 686
    assert all(
        str(item["content_digest"]).startswith("sha256:")
        for item in omitted.values()
    )
    assert len(json.dumps(first, sort_keys=True)) < 10_000
    assert "storage_uri" not in json.dumps(first)


def test_artifact_list_projection_omits_non_json_metadata_fail_closed() -> None:
    projection = project_artifact_list_item_for_agent(
        _Artifact(
            {
                "schema_id": "custom_metadata@1",
                "opaque": object(),
            }
        )
    )

    assert projection["metadata"] == {"schema_id": "custom_metadata@1"}
    summary = projection["metadata_summary"]
    assert summary["metadata_digest"] is None
    assert summary["original_json_chars"] is None
    assert summary["omitted_field_count"] == 1
    assert summary["omitted_fields"][0]["reason"] == "unsupported_value"
    assert summary["omitted_fields"][0]["content_digest"] is None
    json.dumps(projection, sort_keys=True)


def test_artifact_list_projection_uses_encodable_json_for_unicode_budgets() -> None:
    emoji_projection = project_artifact_list_item_for_agent(
        _Artifact({f"field_{index}": "😀" * 500 for index in range(12)})
    )
    emoji_json = serialize_artifact_projection(emoji_projection)

    assert len(emoji_json) <= 20_000
    assert emoji_projection["metadata"] == {}
    assert emoji_projection["metadata_summary"]["omitted_field_count"] == 12
    assert emoji_projection["metadata_summary"]["omitted_fields_truncated"] is True

    surrogate_projection = project_artifact_list_item_for_agent(
        _Artifact({"marker": "\ud800"})
    )
    surrogate_json = serialize_artifact_projection(surrogate_projection)
    assert "\\ud800" in surrogate_json
    surrogate_json.encode("utf-8")


def test_artifact_list_projection_bounds_record_free_text_with_exact_read_hint() -> None:
    projection = project_artifact_list_item_for_agent(
        _Artifact({}, description="x" * 500_000)
    )

    assert "description" not in projection
    record_summary = projection["record_summary"]
    assert record_summary["schema_id"] == "artifact_list_record_summary@1"
    omitted = record_summary["omitted_fields"][0]
    assert omitted["path"] == "artifact.description"
    assert omitted["read_scope"] == "exact_pageable"
    assert "limit=12000" in omitted["read_hint"]
    assert len(serialize_artifact_projection(record_summary)) <= 2_048
    assert len(serialize_artifact_projection(projection)) <= 20_000


def test_artifact_list_projection_keeps_schema_identity_ahead_of_collections() -> None:
    metadata = {
        f"a{index:02d}_digests": [f"sha256:{index:064x}"] * 13
        for index in range(40)
    }
    metadata["schema_id"] = "important_contract@1"
    metadata["provider_contract"] = {
        "contract_id": "provider@2",
        "contract_digest": "sha256:" + "a" * 64,
    }

    projection = project_artifact_list_item_for_agent(_Artifact(metadata))

    assert projection["metadata"]["schema_id"] == "important_contract@1"
    assert projection["metadata"]["provider_contract"]["contract_id"] == "provider@2"


def test_artifact_list_projection_removes_all_private_keys_at_any_depth() -> None:
    metadata: dict[str, Any] = {"schema_id": "safe@1"}
    for private_key in PRIVATE_ARTIFACT_KEYS:
        metadata[f"nested_{private_key}"] = {
            "safe": "visible",
            private_key: f"secret-for-{private_key}",
            "items": [{private_key: f"nested-secret-for-{private_key}"}],
        }

    projection = project_artifact_list_item_for_agent(_Artifact(metadata))
    serialized = serialize_artifact_projection(projection)

    assert "secret-for-" not in serialized
    assert "nested-secret-for-" not in serialized
    assert "safe@1" in serialized


def test_artifact_list_projection_fails_closed_on_recursive_metadata() -> None:
    metadata: dict[str, Any] = {}
    metadata["self"] = metadata

    projection = project_artifact_list_item_for_agent(_Artifact(metadata))

    assert projection["metadata"] == {}
    assert projection["metadata_summary"]["metadata_digest"] is None
    assert projection["metadata_summary"]["omitted_field_count"] >= 1
    serialize_artifact_projection(projection)
