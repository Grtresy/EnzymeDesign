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
from enzymedesign_distribution import validate_hpc_live_bridge_snapshot
from enzymedesign_distribution import verify_live_qualification_receipt_set
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from enzymedesign_distribution import build_external_identity_gaps
from enzymedesign_distribution import build_external_qualification_dry_plan
from enzymedesign_distribution import bind_live_qualification_occurrence_scope
from enzymedesign_distribution import discover_external_subject_identities
from enzymedesign_distribution import exercise_live_qualification_negative_gate
from openzyme_contracts import ExternalQualificationAuthorizationRevocation
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationOccurrenceAuthorization
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import verify_external_qualification_occurrence_authorization
from openzyme_hpc_ssh import SshWorkspaceRuntimeQualificationIdentity
from openzyme_hpc_ssh import DIANNAN_WORKSPACE_RUNTIME_PARENT
from openzyme_hpc_ssh import DIANNAN_WORKSPACE_RUNTIME_PATH
from openzyme_store_sqlite import SQLiteProtectedQualificationLedger
from test_gate.source import collect_source_identity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute exact durable one-shot Batch 1 qualification."
    )
    parser.add_argument("post_preparation_packet", type=Path)
    parser.add_argument("authorization", type=Path)
    parser.add_argument(
        "--unit-digest",
        action="append",
        default=None,
        help=(
            "Execute only this exact dry-plan unit in the occurrence; repeat for "
            "a bounded follow-up subset. The full dry plan remains the authority ceiling."
        ),
    )
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


def _prepared_git_repository(
    *,
    layout: QualificationOperatorStateLayout,
    ledger: SQLiteProtectedQualificationLedger,
    snapshot: SafeIdentitySnapshot,
) -> Path:
    identity_fields = {
        field_id: _field(snapshot, "git-primary", field_id)
        for field_id in (
            "local_repository_endpoint",
            "local_lfs_endpoint_identity",
            "repository_policy_digest",
            "local_process_scope_digest",
        )
    }
    matches = ledger.restore_preparation_results_by_safe_identity(
        owner_component_id="openzyme.workspace.git.lfs",
        safe_identity_fields=identity_fields,
    )
    if len(matches) != 1:
        raise ExternalQualificationError(
            "qualification_git_prepared_identity_not_unique",
            "prepared Git/LFS identity must resolve to exactly one protected occurrence",
        )
    repository_root = layout.root / "git-lfs"
    repository = repository_root / matches[0].occurrence_id
    owner_marker = repository / ".openzyme-qualification-owner"
    if (
        repository.parent != repository_root
        or repository.is_symlink()
        or not repository.is_dir()
        or not owner_marker.is_file()
        or owner_marker.is_symlink()
        or owner_marker.read_text(encoding="utf-8") != matches[0].occurrence_id
    ):
        raise ExternalQualificationError(
            "qualification_git_prepared_repository_invalid",
            "prepared Git/LFS repository does not match its protected owner occurrence",
        )
    return repository


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
    validate_hpc_live_bridge_snapshot(snapshot)
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
    selected_unit_digests = bind_live_qualification_occurrence_scope(
        dry_plan=dry_plan,
        authorization=authorization,
        ledger=ledger,
        source_identity_digest=source.digest,
        selected_unit_digests=(
            None if args.unit_digest is None else tuple(args.unit_digest)
        ),
    )
    preparation_plan_digest = packet.get("preparation_plan_digest")
    preparation_authorization_digest = packet.get(
        "preparation_authorization_digest"
    )
    if not isinstance(preparation_plan_digest, str) or not isinstance(
        preparation_authorization_digest, str
    ):
        raise ValueError("post-preparation packet lacks exact preparation identity")
    git_repository = _prepared_git_repository(
        layout=layout,
        ledger=ledger,
        snapshot=snapshot,
    )
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
        private_diagnostic_root=layout.private_evidence_root,
        git_repository=git_repository,
        image_digests=image_digests,
        hpc_image_digests={
            "hmmer": _field(snapshot, "hmmer-hpc", "hmmer_sif_digest"),
            "vina": _field(snapshot, "vina-hpc", "vina_sif_digest"),
            "fpocket": _field(snapshot, "fpocket-hpc", "fpocket_sif_digest"),
        },
        workspace_runtime_identity=SshWorkspaceRuntimeQualificationIdentity(
            helper_path=DIANNAN_WORKSPACE_RUNTIME_PATH,
            workspace_parent=DIANNAN_WORKSPACE_RUNTIME_PARENT,
            policy_id=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_policy_id",
            ),
            helper_version=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_version",
            ),
            helper_build_digest=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_build_digest",
            ),
            root_policy_digest=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_root_policy_digest",
            ),
            principal_identity_digest=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_principal_identity_digest",
            ),
            deployment_plan_digest=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_deployment_plan_digest",
            ),
            deployment_receipt_digest=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_deployment_receipt_digest",
            ),
            native_qualification_digest=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_native_qualification_digest",
            ),
            file_owner=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_file_owner",
            ),
            file_group=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_file_group",
            ),
            file_mode=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_file_mode",
            ),
            observation_digest=_field(
                snapshot,
                "hpc-control",
                "workspace_runtime_observation_digest",
            ),
        ),
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
            selected_unit_digests=selected_unit_digests,
            revocation=revocation,
        )
        report = ExternalLiveQualificationCoordinator(
            source_identity_digest=source.digest,
            dry_plan=dry_plan,
            readiness_plan=readiness,
            authorization=authorization,
            operator_id="operator.enzymedesign-owner",
            router=router,
            ledger=ledger,
            cleanup_port=factory,
            revocation=revocation,
        ).execute(
            observed_at=observed_at,
            selected_unit_digests=selected_unit_digests,
        )
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
    authorizations: list[ExternalQualificationOccurrenceAuthorization] = []
    for candidate in sorted(layout.root.glob("qualification-authorization-*.json")):
        _validate_private_file(candidate)
        candidate_authorization = ExternalQualificationOccurrenceAuthorization.from_dict(
            _load_object(candidate)
        )
        if candidate_authorization.dry_plan_digest != dry_plan.dry_plan_digest:
            continue
        if _load_revocation(layout, candidate_authorization) is not None:
            continue
        authorizations.append(candidate_authorization)
    receipt_set = verify_live_qualification_receipt_set(
        dry_plan=dry_plan,
        readiness_plan=readiness,
        source_identity_digest=source.digest,
        operator_id="operator.enzymedesign-owner",
        authorizations=tuple(authorizations),
        ledger=ledger,
        verified_at=_now(),
    )
    receipt_set_path = (
        layout.private_evidence_root
        / f"qualification-receipt-set-{authorization.authorization_id}.json"
    )
    _write_private_json(receipt_set_path, receipt_set.to_dict())
    print(f"qualification_report={report_path}")
    print(f"qualification_receipt_set={receipt_set_path}")
    print(f"dry_plan_digest={report.dry_plan_digest}")
    print(f"authorization_digest={report.authorization_digest}")
    print(f"outcome_count={len(report.outcomes)}")
    print(f"receipt_count={len(report.receipts)}")
    print(f"report_digest={report.report_digest}")
    print(f"occurrence_qualified={str(report.occurrence_qualified).lower()}")
    print(f"qualified={str(report.qualified).lower()}")
    print(f"receipt_set_count={len(receipt_set.selected_receipts)}")
    print(f"receipt_set_report_digest={receipt_set.report_digest}")
    print(f"receipt_set_qualified={str(receipt_set.qualified).lower()}")
    print("cutover=false")
    print("fallback_performed=false")
    return 0 if receipt_set.qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
