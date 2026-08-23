#!/usr/bin/env python3
"""Execute or restore one exact authorized Diannan helper deployment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat

from enzymedesign_distribution import ProtectedQualificationCredentialBundleResolver
from enzymedesign_distribution import QUALIFICATION_STATE_ROOT_ENV
from enzymedesign_distribution import QualificationOperatorStateLayout
from openzyme_hpc_ssh import OpenSshQualificationState
from openzyme_hpc_ssh import OpenSshWorkspaceRuntimeDeploymentPort
from openzyme_hpc_ssh import SubprocessOpenSshQualificationCommandPort
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentAuthorization
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentCoordinator
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentPlan
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentReceipt
from openzyme_hpc_ssh import verify_workspace_runtime_deployment_authorization
from openzyme_hpc_ssh import workspace_runtime_source_bytes
from test_gate.source import collect_source_identity


HPC_LOCATOR = "credential.hpc.diannan.qualification"
OPERATOR_ID = "operator.enzymedesign-owner"


def _private_object(path: Path) -> dict[str, object]:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError("deployment evidence file is not private")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("deployment evidence is not one JSON object")
    return payload


def _write_once(path: Path, payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    if path.exists() or path.is_symlink():
        if _private_object(path) != payload:
            raise ValueError("existing deployment receipt conflicts")
        return
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("authorization", type=Path)
    args = parser.parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "1":
        raise SystemExit("OPENZYME_ALLOW_LIVE must be exactly 1")
    raw_root = os.environ.get(QUALIFICATION_STATE_ROOT_ENV)
    if not raw_root:
        raise SystemExit(f"{QUALIFICATION_STATE_ROOT_ENV} is required")
    layout = QualificationOperatorStateLayout.open(Path(raw_root))
    plan = WorkspaceRuntimeDeploymentPlan.from_dict(
        _private_object(args.plan.resolve())
    )
    authorization = WorkspaceRuntimeDeploymentAuthorization.from_dict(
        _private_object(args.authorization.resolve())
    )
    verify_workspace_runtime_deployment_authorization(
        plan,
        authorization,
        expected_operator_id=OPERATOR_ID,
    )
    source = collect_source_identity(Path(__file__).resolve().parents[1])
    if source.digest != plan.source_identity_digest:
        raise ValueError("workspace runtime deployment source identity drifted")
    evidence_root = layout.private_evidence_root
    if not evidence_root.exists():
        evidence_root.mkdir(mode=0o700)
    suffix = authorization.authorization_digest.removeprefix("sha256:")[:24]
    receipt_path = evidence_root / f"workspace-runtime-deployment-receipt-{suffix}.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        receipt = WorkspaceRuntimeDeploymentReceipt.from_dict(
            _private_object(receipt_path)
        )
        if (
            receipt.plan_digest != plan.plan_digest
            or receipt.authorization_digest != authorization.authorization_digest
        ):
            raise ValueError("stored deployment receipt identity drifted")
        print(f"receipt_digest={receipt.receipt_digest}")
        print("restored_without_redispatch=true")
        return 0
    material = ProtectedQualificationCredentialBundleResolver(
        layout=layout,
        allowed_locator_ids=(HPC_LOCATOR,),
    ).resolve(locator_id=HPC_LOCATOR)
    ssh_state = OpenSshQualificationState(
        credential_material=material,
        workspace_id="workspace-runtime-deployment",
        command_port=SubprocessOpenSshQualificationCommandPort(),
    )
    receipt = WorkspaceRuntimeDeploymentCoordinator(
        OpenSshWorkspaceRuntimeDeploymentPort(ssh_state)
    ).execute(
        plan=plan,
        authorization=authorization,
        expected_operator_id=OPERATOR_ID,
        helper_bytes=workspace_runtime_source_bytes(),
    )
    _write_once(receipt_path, receipt.to_dict())
    print(f"receipt_digest={receipt.receipt_digest}")
    print(f"installed_digest={receipt.installed_digest}")
    print("qualified_helper=true")
    print("cutover=false")
    print("fallback_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
