#!/usr/bin/env python3
"""Execute or restore one exact authorized EnzymeDesign Batch 1 qualification."""

from __future__ import annotations

import argparse
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import json
import os
from pathlib import Path
import stat
import sys
import traceback

from enzymedesign_distribution import EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS
from enzymedesign_distribution import OPTIONAL_PROFILES
from enzymedesign_distribution import ExternalLiveQualificationCoordinator
from enzymedesign_distribution import ExternalQualificationBatch
from enzymedesign_distribution import ProtectedQualificationCredentialBundleResolver
from enzymedesign_distribution import QUALIFICATION_STATE_ROOT_ENV
from enzymedesign_distribution import QualificationOperatorStateLayout
from enzymedesign_distribution import SafeIdentitySnapshot
from enzymedesign_distribution import SelectedLiveQualificationBridgeFactory
from enzymedesign_distribution import SelectedQualificationProbeRouter
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from enzymedesign_distribution import build_external_identity_gaps
from enzymedesign_distribution import build_external_qualification_dry_plan
from enzymedesign_distribution import discover_external_subject_identities
from enzymedesign_distribution import exercise_live_qualification_negative_gate
from openzyme_contracts import ExternalQualificationAuthorizationRevocation
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationOccurrenceAuthorization
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import verify_external_qualification_occurrence_authorization
from openzyme_store_sqlite import SQLiteProtectedQualificationLedger
from test_gate.source import collect_source_identity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute exact durable one-shot Batch 1 qualification."
    )
    parser.add_argument("post_preparation_packet", type=Path)
    parser.add_argument("authorization", type=Path)
    return parser


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return payload


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
                "protected qualification directory ownership or mode is unsafe",
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
                "existing qualification evidence differs from the exact occurrence",
            )
        return
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _field(snapshot: SafeIdentitySnapshot, projection_id: str, field_id: str) -> str:
    projection = next(
        item for item in snapshot.projections if item.projection_id == projection_id
    )
    try:
        return {item.field_id: item.value for item in projection.safe_fields}[field_id]
    except KeyError as exc:
        raise ExternalQualificationError(
            "qualification_live_subject_field_missing",
            "prepared subject lacks one exact live bridge field",
        ) from exc


def _load_revocation(
    layout: QualificationOperatorStateLayout,
    authorization: ExternalQualificationOccurrenceAuthorization,
) -> ExternalQualificationAuthorizationRevocation | None:
    suffix = authorization.authorization_digest.removeprefix("sha256:")
    path = layout.private_evidence_root / f"qualification-revocation-{suffix}.json"
    if not path.exists() and not path.is_symlink():
        return None
    _validate_private_file(path)
    return ExternalQualificationAuthorizationRevocation.from_dict(_load_object(path))


def _record_failure(
    *,
    layout: QualificationOperatorStateLayout,
    source_digest: str,
    dry_plan_digest: str,
    authorization_digest: str,
    exc: BaseException,
) -> str:
    error_code = getattr(exc, "error_code", "qualification_execution_failed")
    diagnostic_id = getattr(exc, "diagnostic_id", None) or (
        "diagnostic.qualification."
        + canonical_sha256_digest(
            {
                "source_digest": source_digest,
                "dry_plan_digest": dry_plan_digest,
                "authorization_digest": authorization_digest,
                "error_code": error_code,
            }
        ).removeprefix("sha256:")[:24]
    )
    payload = {
        "schema_version": "enzymedesign_qualification_private_diagnostic@1",
        "diagnostic_id": diagnostic_id,
        "observed_at": _now(),
        "source_identity_digest": source_digest,
        "dry_plan_digest": dry_plan_digest,
        "authorization_digest": authorization_digest,
        "error_code": error_code,
        "component": getattr(exc, "component", "enzymedesign.distribution"),
        "phase": getattr(exc, "phase", "external-qualification"),
        "effect_certainty": getattr(exc, "effect_certainty", "unknown"),
        "mutation_applied": bool(getattr(exc, "mutation_applied", False)),
        "fallback_performed": bool(getattr(exc, "fallback_performed", False)),
        "retry_performed": False,
        "cause_type": type(exc).__name__,
        "cause_message": str(exc)[:8192],
        "bounded_traceback": traceback.format_exc()[-32_768:],
    }
    _ensure_private_directory(layout.private_evidence_root)
    suffix = canonical_sha256_digest(payload).removeprefix("sha256:")[:24]
    _write_private_json(
        layout.private_evidence_root / f"qualification-failure-{suffix}.json",
        payload,
    )
    return diagnostic_id


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "1":
        raise SystemExit("OPENZYME_ALLOW_LIVE must be exactly 1 for qualification")
    raw_root = os.environ.get(QUALIFICATION_STATE_ROOT_ENV)
    if not raw_root:
        raise SystemExit(f"{QUALIFICATION_STATE_ROOT_ENV} is required")
    layout = QualificationOperatorStateLayout.open(Path(raw_root))
    packet_path = args.post_preparation_packet.resolve()
    authorization_path = args.authorization.resolve()
    _validate_private_file(packet_path)
    _validate_private_file(authorization_path)
    packet = _load_object(packet_path)
    source = collect_source_identity(Path(__file__).resolve().parents[1])
    if (
        packet.get("schema_version")
        != "enzymedesign_post_preparation_operator_packet@1"
        or packet.get("claim") != "prepared_not_qualified"
        or packet.get("source_identity_digest") != source.digest
        or packet.get("qualified") is not False
        or packet.get("cutover") is not False
        or packet.get("fallback_performed") is not False
    ):
        raise ExternalQualificationError(
            "qualification_post_preparation_packet_drift",
            "post-preparation packet is not exact current source evidence",
        )
    prepared_snapshot = packet.get("prepared_snapshot")
    if not isinstance(prepared_snapshot, dict):
        raise ValueError("post-preparation packet lacks one safe prepared snapshot")
    snapshot = SafeIdentitySnapshot.from_dict(prepared_snapshot)
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.batch-1.exact-readiness",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
        credential_locator_ids=EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS,
    )
    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    dry_plan = build_external_qualification_dry_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=build_external_identity_gaps(discovery),
        batch=ExternalQualificationBatch.BATCH_1,
    )
    if dry_plan.dry_plan_digest != packet.get(
        "batch_1_qualification_dry_plan_digest"
    ):
        raise ExternalQualificationError(
            "qualification_dry_plan_source_drift",
            "reconstructed Batch 1 dry plan differs from prepared evidence",
        )
    authorization = ExternalQualificationOccurrenceAuthorization.from_dict(
        _load_object(authorization_path)
    )
    observed_at = _now()
    revocation = _load_revocation(layout, authorization)
    verify_external_qualification_occurrence_authorization(
        dry_plan,
        authorization,
        observed_at=observed_at,
        expected_operator_id="operator.enzymedesign-owner",
        revocation=revocation,
    )
    negative_digest = exercise_live_qualification_negative_gate(
        dry_plan=dry_plan,
        readiness_plan=readiness,
        authorization=authorization,
        operator_id="operator.enzymedesign-owner",
        observed_at=observed_at,
    )
    _validate_private_file(layout.ledger_path)
    ledger = SQLiteProtectedQualificationLedger(layout.ledger_path)
    preparation_plan_digest = packet.get("preparation_plan_digest")
    preparation_authorization_digest = packet.get(
        "preparation_authorization_digest"
    )
    if not isinstance(preparation_plan_digest, str) or not isinstance(
        preparation_authorization_digest, str
    ):
        raise ValueError("post-preparation packet lacks exact preparation identity")
    preparation_results = ledger.restore_preparation_results(
        preparation_plan_digest,
        preparation_authorization_digest,
    )
    git_result = next(
        item
        for item in preparation_results
        if item.owner_component_id == "openzyme.workspace.git.lfs"
    )
    git_repository = layout.root / "git-lfs" / git_result.occurrence_id
    image_digests = {
        "base": _field(snapshot, "podman-base", "approved_qualification_image_digest"),
        "hmmer": _field(snapshot, "hmmer-local", "hmmer_image_digest"),
        "docking": _field(snapshot, "vina-local", "vina_image_digest"),
    }
    if len(
        {
            image_digests["docking"],
            _field(snapshot, "fpocket-local", "fpocket_image_digest"),
            _field(snapshot, "preprocess-podman", "preprocess_image_digest"),
        }
    ) != 1:
        raise ExternalQualificationError(
            "qualification_docking_image_identity_drift",
            "Vina, fpocket and preprocess do not share the prepared docking image",
        )
    resolver = ProtectedQualificationCredentialBundleResolver(
        layout=layout,
        allowed_locator_ids=dry_plan.credential_locator_ids,
    )
    factory = SelectedLiveQualificationBridgeFactory(
        credential_resolver=resolver,
        protected_workspace_root=layout.root / "qualification-workspaces",
        git_repository=git_repository,
        image_digests=image_digests,
        tavily_deadline_at=(datetime.now(tz=UTC) + timedelta(minutes=10)).isoformat(),
    )
    try:
        router = SelectedQualificationProbeRouter(
            dry_plan=dry_plan,
            readiness_plan=readiness,
            authorization=authorization,
            operator_id="operator.enzymedesign-owner",
            observed_at=observed_at,
            bridge_builders=factory.builders(),
            revocation=revocation,
        )
        report = ExternalLiveQualificationCoordinator(
            dry_plan=dry_plan,
            readiness_plan=readiness,
            authorization=authorization,
            operator_id="operator.enzymedesign-owner",
            router=router,
            ledger=ledger,
            cleanup_port=factory,
            revocation=revocation,
        ).execute(observed_at=observed_at)
    except Exception as exc:
        diagnostic_id = _record_failure(
            layout=layout,
            source_digest=source.digest,
            dry_plan_digest=dry_plan.dry_plan_digest,
            authorization_digest=authorization.authorization_digest,
            exc=exc,
        )
        print(f"error_code={getattr(exc, 'error_code', 'qualification_execution_failed')}", file=sys.stderr)
        print(f"diagnostic_id={diagnostic_id}", file=sys.stderr)
        print("fallback_performed=false", file=sys.stderr)
        print("retry_performed=false", file=sys.stderr)
        return 1
    if report.negative_test_receipt_digest != negative_digest:
        raise AssertionError("qualification negative gate digest drifted")
    _ensure_private_directory(layout.private_evidence_root)
    report_path = (
        layout.private_evidence_root
        / f"qualification-report-{authorization.authorization_id}.json"
    )
    _write_private_json(report_path, report.to_dict())
    print(f"qualification_report={report_path}")
    print(f"dry_plan_digest={report.dry_plan_digest}")
    print(f"authorization_digest={report.authorization_digest}")
    print(f"outcome_count={len(report.outcomes)}")
    print(f"receipt_count={len(report.receipts)}")
    print(f"report_digest={report.report_digest}")
    print(f"qualified={str(report.qualified).lower()}")
    print("cutover=false")
    print("fallback_performed=false")
    return 0 if report.qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
