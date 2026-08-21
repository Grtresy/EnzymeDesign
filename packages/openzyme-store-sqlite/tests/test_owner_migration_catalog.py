from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from openzyme_contracts import canonical_sha256_digest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOG = (
    REPOSITORY_ROOT
    / "packages/openzyme-store-sqlite/src/openzyme_store_sqlite/manifests"
    / "migration-catalog.json"
)


def test_owner_partitioned_migration_catalog_is_closed_and_reproducible() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "scripts/partition-openzyme-sqlite-schema.py"),
            "--check",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    observation = json.loads(completed.stdout)
    assert observation["mutation_applied"] is False
    assert observation["bundle_count"] == 25
    assert observation["object_counts"] == {
        "tables": 147,
        "indexes": 134,
        "triggers": 674,
        "foreign_keys": 422,
    }


def test_each_bundle_has_one_owner_and_exact_digest() -> None:
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    payload = {key: value for key, value in document.items() if key != "catalog_digest"}
    assert document["catalog_digest"] == canonical_sha256_digest(payload)
    assert len(document["bundle_order"]) == len(set(document["bundle_order"]))
    assert document["bundle_order"] == [
        bundle["migration_id"] for bundle in document["bundles"]
    ]

    seen_objects: set[str] = set()
    for bundle in document["bundles"]:
        path = (
            REPOSITORY_ROOT
            / "packages/openzyme-store-sqlite/src/openzyme_store_sqlite"
            / bundle["resource"]
        )
        observed_digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert observed_digest == bundle["resource_digest"]
        assert bundle["object_count"] == len(bundle["object_identities"])
        assert not seen_objects.intersection(bundle["object_identities"])
        seen_objects.update(bundle["object_identities"])

    assert len(seen_objects) == 147 + 134 + 674 + 2
