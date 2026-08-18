#!/usr/bin/env python3
"""Standalone empty-cache verifier for migrated immutable historical Git/LFS data."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from offline_historical_migrator import MigrationBlocked
from offline_historical_migrator import RECEIPT_SCHEMA
from offline_historical_migrator import FrozenObject
from offline_historical_migrator import FrozenReference
from offline_historical_migrator import digest
from offline_historical_migrator import require_digest
from offline_historical_migrator import operator_source_digests
from offline_historical_migrator import fresh_readback


def verify(
    receipt_path: Path,
    remote_url: str,
    *,
    working_root: Path,
) -> dict[str, object]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        raise MigrationBlocked("historical migration receipt schema is unsupported")
    declared = receipt.get("receipt_digest")
    payload = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if declared != digest(payload):
        raise MigrationBlocked("historical migration receipt digest mismatch")
    exact_pairs = (
        ("expected_identity_set_digest", "migrated_identity_set_digest"),
        ("expected_reference_set_digest", "migrated_reference_set_digest"),
        ("expected_byte_total", "migrated_byte_total"),
    )
    if any(receipt[left] != receipt[right] for left, right in exact_pairs):
        raise MigrationBlocked("historical receipt exact-set equality is false")
    if any(
        int(receipt.get(name, -1)) != 0
        for name in (
            "unresolved_reference_count",
            "post_freeze_write_count",
            "negative_item_count",
        )
    ):
        raise MigrationBlocked("historical receipt contains unresolved negative items")
    if receipt.get("aox_non_adoption_proven") is not True:
        raise MigrationBlocked("AOX non-adoption proof is absent")
    if receipt.get("source_preserved") is not True:
        raise MigrationBlocked("migration did not preserve its frozen source")
    current_sources = operator_source_digests()
    if (
        receipt.get("operator_source_digests") != current_sources
        or receipt.get("operator_source_set_digest") != digest(current_sources)
    ):
        raise MigrationBlocked("historical verifier source identity differs")
    objects = receipt.get("objects")
    frozen_objects_raw = receipt.get("frozen_objects")
    frozen_references_raw = receipt.get("frozen_references")
    targets = receipt.get("targets")
    rewrites = receipt.get("reference_rewrites")
    unit_receipts = receipt.get("unit_receipts")
    if (
        not isinstance(objects, list)
        or not isinstance(frozen_objects_raw, list)
        or not isinstance(frozen_references_raw, list)
        or not isinstance(targets, list)
        or not isinstance(rewrites, list)
        or not isinstance(unit_receipts, list)
    ):
        raise MigrationBlocked("historical mapping or target set is malformed")
    frozen_objects = tuple(
        FrozenObject.from_dict(item) for item in frozen_objects_raw
    )
    frozen_references = tuple(
        FrozenReference.from_dict(item) for item in frozen_references_raw
    )
    storage_observation = receipt.get("storage_snapshot_observation")
    root_digests = receipt.get("source_root_path_digests")
    if (
        not isinstance(storage_observation, dict)
        or storage_observation.get("schema")
        != "historical_storage_snapshot_observation@1"
        or digest(storage_observation) != receipt.get("storage_snapshot_digest")
        or storage_observation.get("object_source_identity_digests")
        != sorted(item.source_identity_digest for item in frozen_objects)
        or not isinstance(root_digests, dict)
    ):
        raise MigrationBlocked("historical physical storage snapshot differs")
    for root_id, root_digest in root_digests.items():
        if not root_id:
            raise MigrationBlocked("historical source root identity is empty")
        require_digest(root_digest, "source_root_path_digest")
    if receipt.get("expected_identity_set_digest") != digest(
        sorted(digest(item.identity) for item in frozen_objects)
    ) or receipt.get("expected_reference_set_digest") != digest(
        sorted(digest(asdict(item)) for item in frozen_references)
    ):
        raise MigrationBlocked("frozen inventory exact-set identity differs")
    if any(
        not isinstance(item, dict)
        or item.get("eligibility") != "historical_import_non_adoptable"
        or item.get("supersession_decision_digest")
        != digest(
            {
                "original_id": item.get("original_id"),
                "decision": "historical_import_non_adoptable",
                "current_adoption_authorized": False,
            }
        )
        for item in objects
    ):
        raise MigrationBlocked("historical mapping is adoptable or malformed")
    if any(
        not isinstance(item, dict)
        or item.get("mapping_digest")
        != digest({key: value for key, value in item.items() if key != "mapping_digest"})
        for item in objects
    ) or receipt.get("mapping_set_digest") != digest(
        sorted(str(item["mapping_digest"]) for item in objects if isinstance(item, dict))
    ):
        raise MigrationBlocked("historical mapping set digest differs")
    if receipt.get("non_adoption_set_digest") != digest(
        sorted(str(item["supersession_decision_digest"]) for item in objects)
    ):
        raise MigrationBlocked("historical non-adoption set digest differs")
    if any(
        not isinstance(item, dict)
        or item.get("rewrite_digest")
        != digest({key: value for key, value in item.items() if key != "rewrite_digest"})
        for item in rewrites
    ) or receipt.get("rewritten_reference_set_digest") != digest(
        sorted(str(item["rewrite_digest"]) for item in rewrites if isinstance(item, dict))
    ):
        raise MigrationBlocked("historical typed rewrite set digest differs")
    unit_digests = []
    for item in unit_receipts:
        if not isinstance(item, dict):
            raise MigrationBlocked("historical unit receipt is malformed")
        unit_payload = {
            key: value
            for key, value in item.items()
            if key not in {"receipt_id", "receipt_digest"}
        }
        if (
            item.get("receipt_digest") != digest(unit_payload)
            or item.get("expected_identity_set_digest")
            != item.get("migrated_identity_set_digest")
            or item.get("zero_post_freeze_write") is not True
        ):
            raise MigrationBlocked("historical unit receipt identity differs")
        unit_digests.append(str(item["receipt_digest"]))
    if receipt.get("unit_receipt_set_digest") != digest(sorted(unit_digests)):
        raise MigrationBlocked("historical unit receipt set digest differs")
    mapped_ids = {
        str(item["original_id"])
        for item in objects
        if isinstance(item, dict) and "original_id" in item
    }
    target_ids = {
        str(item["object_id"])
        for target in targets
        if isinstance(target, dict)
        for item in target.get("objects", [])
        if isinstance(item, dict) and "object_id" in item
    }
    if (
        len(mapped_ids) != len(objects)
        or len(target_ids) != len(objects)
        or mapped_ids != target_ids
        or mapped_ids != {item.object_id for item in frozen_objects}
    ):
        raise MigrationBlocked("historical mapping and target identity sets differ")
    mapping_by_id = {
        str(item["original_id"]): item for item in objects if isinstance(item, dict)
    }
    rewrites_by_id = {
        str(item["reference_id"]): item
        for item in rewrites
        if isinstance(item, dict) and "reference_id" in item
    }
    if set(rewrites_by_id) != {item.reference_id for item in frozen_references}:
        raise MigrationBlocked("historical frozen reference set differs")
    for reference in frozen_references:
        rewrite = rewrites_by_id[reference.reference_id]
        expected_ref = (
            mapping_by_id[reference.object_id]["historical_ref_id"]
            if reference.replacement_kind == "historical_ref"
            else reference.expected_replacement_ref
        )
        if (
            rewrite.get("source_table") != reference.source_table
            or rewrite.get("source_primary_key") != reference.source_primary_key
            or rewrite.get("source_field") != reference.source_field
            or rewrite.get("replacement_field") != reference.replacement_field
            or rewrite.get("original_id") != reference.object_id
            or rewrite.get("replacement_kind") != reference.replacement_kind
            or rewrite.get("replacement_ref") != expected_ref
            or rewrite.get("source_row_version_digest")
            != reference.source_row_version_digest
            or rewrite.get("replacement_identity_digest")
            != digest({"kind": reference.replacement_kind, "ref": expected_ref})
        ):
            raise MigrationBlocked("historical typed reference rewrite differs")
    target_by_id = {
        str(item["object_id"]): (target, item)
        for target in targets
        if isinstance(target, dict)
        for item in target.get("objects", [])
        if isinstance(item, dict)
    }
    for object_id, mapping in mapping_by_id.items():
        target, target_item = target_by_id[object_id]
        exact_pairs = (
            (mapping.get("historical_ref"), target.get("historical_ref")),
            (mapping.get("commit"), target.get("commit")),
            (mapping.get("tree"), target.get("tree")),
            (mapping.get("path"), target_item.get("path")),
            (mapping.get("content_digest"), target_item.get("content_digest")),
            (mapping.get("size"), target_item.get("size")),
            (mapping.get("storage"), target_item.get("storage")),
            (mapping.get("git_blob_oid"), target_item.get("git_blob_oid")),
            (mapping.get("lfs_oid"), target_item.get("lfs_oid")),
            (mapping.get("lfs_size"), target_item.get("lfs_size")),
            (
                mapping.get("owner_identity_digest"),
                target_item.get("owner_identity_digest"),
            ),
            (mapping.get("lineage_digest"), target_item.get("lineage_digest")),
        )
        if any(left != right for left, right in exact_pairs):
            raise MigrationBlocked("historical mapping target lineage differs")
    readbacks = tuple(
        fresh_readback(
            remote_url=remote_url,
            target=target,
            working_root=working_root,
        )
        for target in targets
        if isinstance(target, dict)
    )
    if len(readbacks) != len(targets):
        raise MigrationBlocked("historical target set contains a malformed entry")
    observed = {
        "schema": "historical_artifact_standalone_verification@1",
        "receipt_digest": declared,
        "readback_set_digest": digest(readbacks),
        "verified_target_count": len(readbacks),
        "verified_object_count": len(objects),
        "historical_only": True,
        "current_adoption_authorized": False,
    }
    if observed["readback_set_digest"] != receipt["readback_set_digest"]:
        raise MigrationBlocked("empty-cache readback set differs from the receipt")
    return {**observed, "verification_digest": digest(observed)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--remote-url", required=True)
    parser.add_argument("--working-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            verify(
                args.receipt,
                args.remote_url,
                working_root=args.working_root,
            ),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
