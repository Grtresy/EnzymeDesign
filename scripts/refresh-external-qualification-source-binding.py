#!/usr/bin/env python3
"""Rebind prepared Batch 1 evidence to the exact current source without effects."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat

from enzymedesign_distribution import EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS
from enzymedesign_distribution import OPTIONAL_PROFILES
from enzymedesign_distribution import SafeIdentitySnapshot
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from enzymedesign_distribution import qualification_plan_bundle
from openzyme_contracts import canonical_sha256_digest
from test_gate.source import collect_source_identity


_PROVENANCE_FIELDS = (
    "preparation_plan_digest",
    "preparation_authorization_digest",
    "preparation_result_digests",
    "workspace_runtime_deployment_plan_digest",
    "workspace_runtime_deployment_authorization_digest",
    "workspace_runtime_deployment_receipt_digest",
    "workspace_runtime_native_qualification_digest",
    "workspace_runtime_observation_digest",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prior_packet", type=Path)
    parser.add_argument("output", type=Path)
    return parser


def _load_private(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    metadata = resolved.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise ValueError("source-rebinding input is not an owner-only private file")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("source-rebinding input is not one object")
    return payload


def _write_private(path: Path, payload: dict[str, object]) -> None:
    resolved = path.resolve()
    parent = resolved.parent.lstat()
    if (
        stat.S_ISLNK(parent.st_mode)
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
        or resolved.exists()
        or resolved.is_symlink()
    ):
        raise ValueError("source-rebinding output boundary is unsafe")
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(resolved, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_prior_packet(prior: dict[str, object]) -> SafeIdentitySnapshot:
    digest = prior.get("packet_digest")
    unsigned = dict(prior)
    unsigned.pop("packet_digest", None)
    if (
        prior.get("schema_version")
        != "enzymedesign_post_preparation_operator_packet@1"
        or prior.get("claim") != "prepared_not_qualified"
        or prior.get("qualified") is not False
        or prior.get("cutover") is not False
        or prior.get("fallback_performed") is not False
        or digest != canonical_sha256_digest(unsigned)
    ):
        raise ValueError("prior post-preparation packet is not exact eligible evidence")
    prepared = prior.get("prepared_snapshot")
    if not isinstance(prepared, dict):
        raise ValueError("prior packet lacks one prepared snapshot")
    return SafeIdentitySnapshot.from_dict(prepared)


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "0":
        raise SystemExit("source rebinding requires OPENZYME_ALLOW_LIVE=0")
    prior = _load_private(args.prior_packet)
    snapshot = _verify_prior_packet(prior)
    source = collect_source_identity(Path(__file__).resolve().parents[1])
    if source.tracked_dirty_paths or source.relevant_untracked_sources:
        raise ValueError("source rebinding requires one clean exact checkout")
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.batch-1.exact-readiness",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
        credential_locator_ids=EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS,
    )
    rediscovery = qualification_plan_bundle(
        readiness_plan=readiness,
        snapshot=snapshot,
        selection_set=None,
    )
    dry_plan = next(
        item
        for item in rediscovery["dry_plans"]
        if item["batch_id"] == "batch-1"  # type: ignore[index,union-attr]
    )
    if (
        rediscovery["summary"]["batch_1_authorizable"] is not True  # type: ignore[index]
        or dry_plan["authorizable"] is not True  # type: ignore[index]
    ):
        raise ValueError("prepared Batch 1 identity is not currently authorizable")
    document: dict[str, object] = {
        "schema_version": "enzymedesign_post_preparation_operator_packet@1",
        "claim": "prepared_not_qualified",
        "source_identity": source.as_dict(),
        "source_identity_digest": source.digest,
        "source_rebinding_prior_packet_digest": prior["packet_digest"],
        "prepared_snapshot": snapshot.to_dict(),
        "rediscovery": rediscovery,
        "batch_1_qualification_dry_plan_digest": dry_plan["dry_plan_digest"],  # type: ignore[index]
        "credential_material_persisted": False,
        "qualified": False,
        "cutover": False,
        "fallback_performed": False,
    }
    for field_name in _PROVENANCE_FIELDS:
        if field_name in prior:
            document[field_name] = prior[field_name]
    document["packet_digest"] = canonical_sha256_digest(document)
    _write_private(args.output, document)
    print(f"source_identity_digest={source.digest}")
    print(f"prior_packet_digest={prior['packet_digest']}")
    print(f"packet_digest={document['packet_digest']}")
    print(
        "batch_1_qualification_dry_plan_digest="
        f"{document['batch_1_qualification_dry_plan_digest']}"
    )
    print("external_effect_performed=false")
    print("credential_material_accessed=false")
    print("qualified=false")
    print("cutover=false")
    print("fallback_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
