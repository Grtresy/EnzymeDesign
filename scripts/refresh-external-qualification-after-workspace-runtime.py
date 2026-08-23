#!/usr/bin/env python3
"""Rebind Batch 1 to an exact deployed workspace-runtime identity, without qualification."""

from __future__ import annotations

import argparse
from datetime import UTC
from datetime import datetime
import json
import os
from pathlib import Path
import stat

from enzymedesign_distribution import EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS
from enzymedesign_distribution import OPTIONAL_PROFILES
from enzymedesign_distribution import ProtectedQualificationCredentialBundleResolver
from enzymedesign_distribution import QUALIFICATION_STATE_ROOT_ENV
from enzymedesign_distribution import QualificationOperatorStateLayout
from enzymedesign_distribution import SafeIdentitySnapshot
from enzymedesign_distribution import augment_prepared_snapshot_with_workspace_runtime
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from enzymedesign_distribution import qualification_plan_bundle
from openzyme_contracts import canonical_sha256_digest
from openzyme_hpc_ssh import OpenSshQualificationState
from openzyme_hpc_ssh import SubprocessOpenSshQualificationCommandPort
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentAuthorization
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentPlan
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentReceipt
from openzyme_hpc_ssh import observe_diannan_workspace_runtime_identity
from openzyme_hpc_ssh import verify_workspace_runtime_deployment_authorization
from test_gate.source import collect_source_identity


HPC_LOCATOR = "credential.hpc.diannan.qualification"
OPERATOR_ID = "operator.enzymedesign-owner"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("prior_packet", type=Path)
    parser.add_argument("deployment_plan", type=Path)
    parser.add_argument("deployment_authorization", type=Path)
    parser.add_argument("deployment_receipt", type=Path)
    parser.add_argument("snapshot_output", type=Path)
    parser.add_argument("packet_output", type=Path)
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
        raise ValueError("workspace runtime rediscovery input is not private")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workspace runtime rediscovery input is not one object")
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
        raise ValueError("workspace runtime rediscovery output boundary is unsafe")
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(resolved, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _required_string(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"prior packet lacks {field_name}")
    return value


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "1":
        raise SystemExit("workspace runtime target rediscovery requires OPENZYME_ALLOW_LIVE=1")
    raw_root = os.environ.get(QUALIFICATION_STATE_ROOT_ENV)
    if not raw_root:
        raise SystemExit(f"{QUALIFICATION_STATE_ROOT_ENV} is required")
    layout = QualificationOperatorStateLayout.open(Path(raw_root))
    prior = _load_private(args.prior_packet)
    if (
        prior.get("schema_version")
        != "enzymedesign_post_preparation_operator_packet@1"
        or prior.get("claim") != "prepared_not_qualified"
        or prior.get("qualified") is not False
        or prior.get("cutover") is not False
        or prior.get("fallback_performed") is not False
    ):
        raise ValueError("prior post-preparation packet is not eligible")
    prior_digest = prior.get("packet_digest")
    prior_without_digest = dict(prior)
    prior_without_digest.pop("packet_digest", None)
    if prior_digest != canonical_sha256_digest(prior_without_digest):
        raise ValueError("prior post-preparation packet digest drifted")
    prepared = prior.get("prepared_snapshot")
    if not isinstance(prepared, dict):
        raise ValueError("prior packet lacks a prepared snapshot")
    snapshot = SafeIdentitySnapshot.from_dict(prepared)
    plan = WorkspaceRuntimeDeploymentPlan.from_dict(
        _load_private(args.deployment_plan)
    )
    authorization = WorkspaceRuntimeDeploymentAuthorization.from_dict(
        _load_private(args.deployment_authorization)
    )
    receipt = WorkspaceRuntimeDeploymentReceipt.from_dict(
        _load_private(args.deployment_receipt)
    )
    verify_workspace_runtime_deployment_authorization(
        plan,
        authorization,
        expected_operator_id=OPERATOR_ID,
    )
    if (
        receipt.plan_digest != plan.plan_digest
        or receipt.authorization_digest != authorization.authorization_digest
    ):
        raise ValueError("workspace runtime receipt binding drifted")
    source = collect_source_identity(Path(__file__).resolve().parents[1])
    material = ProtectedQualificationCredentialBundleResolver(
        layout=layout,
        allowed_locator_ids=(HPC_LOCATOR,),
    ).resolve(locator_id=HPC_LOCATOR)
    state = OpenSshQualificationState(
        credential_material=material,
        workspace_id="workspace-runtime-identity-rediscovery",
        command_port=SubprocessOpenSshQualificationCommandPort(),
    )
    identity = observe_diannan_workspace_runtime_identity(
        state=state,
        deployment_plan_digest=plan.plan_digest,
        deployment_receipt_digest=receipt.receipt_digest,
        native_qualification_digest=receipt.native_qualification_digest,
    )
    refreshed = augment_prepared_snapshot_with_workspace_runtime(
        snapshot=snapshot,
        identity=identity,
        deployment_plan=plan,
        deployment_receipt=receipt,
        source_identity_digest=source.digest,
        observed_at=datetime.now(tz=UTC).isoformat(),
    )
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.batch-1.exact-readiness",
        created_at=refreshed.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
        credential_locator_ids=EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS,
    )
    rediscovery = qualification_plan_bundle(
        readiness_plan=readiness,
        snapshot=refreshed,
        selection_set=None,
    )
    if rediscovery["summary"]["batch_1_authorizable"] is not True:  # type: ignore[index]
        raise ValueError("Batch 1 remains blocked after workspace runtime rediscovery")
    dry_plan = next(
        item
        for item in rediscovery["dry_plans"]
        if item["batch_id"] == "batch-1"  # type: ignore[index,union-attr]
    )
    document = {
        "schema_version": "enzymedesign_post_preparation_operator_packet@1",
        "claim": "prepared_not_qualified",
        "source_identity": source.as_dict(),
        "source_identity_digest": source.digest,
        "preparation_plan_digest": _required_string(
            prior,
            "preparation_plan_digest",
        ),
        "preparation_authorization_digest": _required_string(
            prior,
            "preparation_authorization_digest",
        ),
        "preparation_result_digests": prior.get("preparation_result_digests"),
        "workspace_runtime_deployment_plan_digest": plan.plan_digest,
        "workspace_runtime_deployment_authorization_digest": (
            authorization.authorization_digest
        ),
        "workspace_runtime_deployment_receipt_digest": receipt.receipt_digest,
        "workspace_runtime_native_qualification_digest": (
            receipt.native_qualification_digest
        ),
        "workspace_runtime_observation_digest": identity.observation_digest,
        "prepared_snapshot": refreshed.to_dict(),
        "rediscovery": rediscovery,
        "batch_1_qualification_dry_plan_digest": dry_plan["dry_plan_digest"],
        "credential_material_persisted": False,
        "qualified": False,
        "cutover": False,
        "fallback_performed": False,
    }
    document["packet_digest"] = canonical_sha256_digest(document)
    _write_private(args.snapshot_output, refreshed.to_dict())
    _write_private(args.packet_output, document)
    print(f"source_identity_digest={source.digest}")
    print(f"workspace_runtime_observation_digest={identity.observation_digest}")
    print(f"batch_1_qualification_dry_plan_digest={dry_plan['dry_plan_digest']}")
    print("batch_1_authorizable=true")
    print("target_read_performed=true")
    print("mutation_performed=false")
    print("qualified=false")
    print("cutover=false")
    print("fallback_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
