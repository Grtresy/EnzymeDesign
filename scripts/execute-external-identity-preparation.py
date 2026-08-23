#!/usr/bin/env python3
"""Execute one exact authorized EnzymeDesign identity-preparation Batch 1."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC
from datetime import datetime
import json
import os
from pathlib import Path
import stat
from typing import Any

from enzymedesign_distribution import EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS
from enzymedesign_distribution import OPTIONAL_PROFILES
from enzymedesign_distribution import ExternalQualificationBatch
from enzymedesign_distribution import ProtectedQualificationCredentialBundleResolver
from enzymedesign_distribution import QUALIFICATION_STATE_ROOT_ENV
from enzymedesign_distribution import QualificationOperatorStateLayout
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from enzymedesign_distribution import (
    build_enzymedesign_identity_preparation_backend_factory,
)
from enzymedesign_distribution import build_external_identity_gaps
from enzymedesign_distribution import build_external_identity_preparation_plan
from enzymedesign_distribution import build_external_identity_resolution_decisions
from enzymedesign_distribution import discover_external_subject_identities
from enzymedesign_distribution import execute_enzymedesign_identity_preparation_batch
from enzymedesign_distribution import load_operator_identity_resolution_selections
from enzymedesign_distribution import load_safe_identity_snapshot
from enzymedesign_distribution import (
    preflight_enzymedesign_identity_preparation_credentials,
)
from enzymedesign_distribution import qualification_plan_bundle
from openzyme_contracts import ExternalIdentityPreparationOccurrenceAuthorization
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import (
    verify_external_identity_preparation_occurrence_authorization,
)
from openzyme_store_sqlite import SQLiteProtectedQualificationLedger
from test_gate.source import collect_source_identity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute exact authorized Batch 1 identity preparation."
    )
    parser.add_argument("operator_packet", type=Path)
    parser.add_argument("safe_snapshot", type=Path)
    parser.add_argument("decision_selections", type=Path)
    parser.add_argument("authorization", type=Path)
    return parser


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return payload


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _validate_private_file(path: Path) -> None:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise ExternalQualificationError(
            "qualification_operator_state_permissions_unsafe",
            "protected qualification file ownership or mode is unsafe",
        )


def _ensure_private_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise ExternalQualificationError(
                "qualification_operator_state_permissions_unsafe",
                "protected evidence directory ownership or mode is unsafe",
            )
        return
    path.mkdir(mode=0o700, parents=False)


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if path.exists() or path.is_symlink():
        _validate_private_file(path)
        if path.read_bytes() != encoded:
            raise ExternalQualificationError(
                "qualification_private_evidence_conflict",
                "existing private evidence differs from the exact occurrence",
            )
        return
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _batch_1_plan(
    *,
    snapshot: Any,
    selection_set: Any,
    source_digest: str,
) -> tuple[Any, Any]:
    rebound_snapshot = replace(snapshot, source_digest=source_digest)
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id=f"qualification.readiness.{rebound_snapshot.snapshot_id}",
        created_at=rebound_snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=rebound_snapshot,
    )
    gaps = build_external_identity_gaps(discovery)
    decisions = build_external_identity_resolution_decisions(
        gaps=gaps,
        snapshot=rebound_snapshot,
        selection_set=selection_set,
    )
    plan = build_external_identity_preparation_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=gaps,
        decisions=decisions,
        selection_set=selection_set,
        batch=ExternalQualificationBatch.BATCH_1,
    )
    return rebound_snapshot, plan


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "1":
        raise SystemExit("OPENZYME_ALLOW_LIVE must be exactly 1 for preparation")
    raw_root = os.environ.get(QUALIFICATION_STATE_ROOT_ENV)
    if not raw_root:
        raise SystemExit(f"{QUALIFICATION_STATE_ROOT_ENV} is required")

    source = collect_source_identity(Path(__file__).resolve().parents[1])
    packet = _load_object(args.operator_packet.resolve())
    if (
        packet.get("schema_version")
        != "enzymedesign_external_qualification_operator_packet@1"
        or packet.get("claim") != "plan_only"
        or packet.get("source_identity_digest") != source.digest
        or packet.get("credential_material_accessed") is not False
        or packet.get("external_effect_performed") is not False
        or packet.get("fallback_performed") is not False
    ):
        raise ExternalQualificationError(
            "qualification_preparation_operator_packet_drift",
            "operator packet is not the exact current no-effect source-bound packet",
        )

    snapshot, plan = _batch_1_plan(
        snapshot=load_safe_identity_snapshot(args.safe_snapshot.resolve()),
        selection_set=load_operator_identity_resolution_selections(
            args.decision_selections.resolve()
        ),
        source_digest=source.digest,
    )
    embedded_plans = packet.get("identity_preparation_plans")
    if not isinstance(embedded_plans, list):
        raise ValueError("operator packet has no preparation plan list")
    embedded = next(
        (
            item
            for item in embedded_plans
            if isinstance(item, dict) and item.get("batch_id") == "batch-1"
        ),
        None,
    )
    if embedded != plan.to_dict():
        raise ExternalQualificationError(
            "qualification_preparation_operator_packet_drift",
            "embedded Batch 1 preparation plan differs from current source",
        )

    authorization = ExternalIdentityPreparationOccurrenceAuthorization.from_dict(
        _load_object(args.authorization.resolve())
    )
    verify_external_identity_preparation_occurrence_authorization(
        plan,
        authorization,
        observed_at=_now(),
    )
    layout = QualificationOperatorStateLayout.open(Path(raw_root))

    resolver = ProtectedQualificationCredentialBundleResolver(
        layout=layout,
        allowed_locator_ids=plan.credential_locator_ids,
    )
    preloaded = preflight_enzymedesign_identity_preparation_credentials(
        plan=plan,
        resolver=resolver,
    )

    existing_results = ()
    if layout.ledger_path.exists() or layout.ledger_path.is_symlink():
        _validate_private_file(layout.ledger_path)
        existing_results = SQLiteProtectedQualificationLedger(
            layout.ledger_path
        ).restore_preparation_results(plan.preparation_plan_digest)
    factory = build_enzymedesign_identity_preparation_backend_factory(
        layout=layout,
        allowed_locator_ids=plan.credential_locator_ids,
        credential_resolver=preloaded,
    )
    execution = execute_enzymedesign_identity_preparation_batch(
        plan=plan,
        authorization=authorization,
        snapshot=snapshot,
        factory=factory,
        clock=_now,
        existing_results=existing_results,
    )

    exact_readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.batch-1.exact-readiness",
        created_at=execution.prepared_snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
        credential_locator_ids=EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS,
    )
    rediscovered = qualification_plan_bundle(
        readiness_plan=exact_readiness,
        snapshot=execution.prepared_snapshot,
        selection_set=None,
    )
    if rediscovered["summary"]["batch_1_authorizable"] is not True:  # type: ignore[index]
        raise ExternalQualificationError(
            "qualification_preparation_rediscovery_incomplete",
            "Batch 1 remains blocked after exact preparation results",
        )
    qualification_plan = next(
        item for item in rediscovered["dry_plans"] if item["batch_id"] == "batch-1"  # type: ignore[index,union-attr]
    )
    document = {
        "schema_version": "enzymedesign_post_preparation_operator_packet@1",
        "claim": "prepared_not_qualified",
        "source_identity": source.as_dict(),
        "source_identity_digest": source.digest,
        "preparation_plan_digest": execution.plan_digest,
        "preparation_authorization_digest": execution.authorization_digest,
        "preparation_result_digests": [
            item.result_digest for item in execution.results
        ],
        "prepared_snapshot": execution.prepared_snapshot.to_dict(),
        "rediscovery": rediscovered,
        "batch_1_qualification_dry_plan_digest": qualification_plan[
            "dry_plan_digest"
        ],
        "credential_material_persisted": False,
        "qualified": False,
        "cutover": False,
        "fallback_performed": False,
    }
    document["packet_digest"] = canonical_sha256_digest(document)

    _ensure_private_directory(layout.private_evidence_root)
    suffix = authorization.authorization_id
    _write_private_json(
        layout.private_evidence_root / f"prepared-snapshot-{suffix}.json",
        execution.prepared_snapshot.to_dict(),
    )
    _write_private_json(
        layout.private_evidence_root / f"post-preparation-packet-{suffix}.json",
        document,
    )
    print(f"preparation_plan_digest={execution.plan_digest}")
    print(f"preparation_authorization_digest={execution.authorization_digest}")
    print(f"preparation_result_count={len(execution.results)}")
    print(f"post_preparation_packet_digest={document['packet_digest']}")
    print(
        "batch_1_qualification_dry_plan_digest="
        f"{document['batch_1_qualification_dry_plan_digest']}"
    )
    print("qualified=false")
    print("cutover=false")
    print("fallback_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
