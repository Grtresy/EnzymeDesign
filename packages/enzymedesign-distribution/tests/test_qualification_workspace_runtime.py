from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest

from enzymedesign_distribution import SafeIdentitySnapshot
from enzymedesign_distribution import SafeSubjectProjection
from enzymedesign_distribution import augment_prepared_snapshot_with_workspace_runtime
from enzymedesign_distribution import validate_hpc_live_bridge_snapshot
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationSubjectKind
from openzyme_contracts import ExternalSubjectIdentityStatus
from openzyme_contracts import SafeIdentityField
from openzyme_contracts import canonical_sha256_digest
from openzyme_hpc import HpcQualificationIdentityObservation
from openzyme_hpc_ssh import SshWorkspaceRuntimeQualificationIdentity
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentPlan
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentReceipt
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentScope
from openzyme_hpc_ssh import WorkspaceRuntimeDestinationState


DIGEST = "sha256:" + "1" * 64


def _plan() -> WorkspaceRuntimeDeploymentPlan:
    return WorkspaceRuntimeDeploymentPlan.create(
        source_identity_digest=DIGEST,
        target_subject_digest="sha256:" + "2" * 64,
        target_host_key_digest="sha256:" + "3" * 64,
        helper_build_digest="sha256:" + "4" * 64,
        helper_version="1.0.0",
        target_login="grtresy",
        target_home="/home/grtresy",
        deployment_scope=(
            WorkspaceRuntimeDeploymentScope.TARGET_PRINCIPAL_USER_LIBEXEC
        ),
        destination_state=WorkspaceRuntimeDestinationState.MISSING,
        destination_pre_digest=None,
        installer_identity="principal.grtresy.diannan",
        privilege_mechanism="direct-user-libexec-v1",
        rollback_owner="principal.grtresy.diannan",
        file_owner="grtresy",
        file_group="grtresy",
    )


def _receipt(plan: WorkspaceRuntimeDeploymentPlan) -> WorkspaceRuntimeDeploymentReceipt:
    return WorkspaceRuntimeDeploymentReceipt.create(
        plan_digest=plan.plan_digest,
        authorization_digest="sha256:" + "5" * 64,
        installed_digest=plan.helper_build_digest,
        destination_pre_digest=None,
        native_qualification_digest="sha256:" + "6" * 64,
        rollback_performed=False,
        fallback_performed=False,
    )


def _identity(
    plan: WorkspaceRuntimeDeploymentPlan,
    receipt: WorkspaceRuntimeDeploymentReceipt,
) -> SshWorkspaceRuntimeQualificationIdentity:
    payload = {
        "helper_path": plan.destination_path,
        "workspace_parent": plan.workspace_parent,
        "policy_id": "policy.openzyme.hpc.diannan.workspace-runtime",
        "helper_version": "1.0.0",
        "helper_build_digest": plan.helper_build_digest,
        "root_policy_digest": "sha256:" + "7" * 64,
        "principal_identity_digest": "sha256:" + "8" * 64,
        "deployment_plan_digest": plan.plan_digest,
        "deployment_receipt_digest": receipt.receipt_digest,
        "native_qualification_digest": receipt.native_qualification_digest,
        "file_owner": "grtresy",
        "file_group": "grtresy",
        "file_mode": "755",
    }
    return SshWorkspaceRuntimeQualificationIdentity(
        **payload,
        observation_digest=canonical_sha256_digest(payload),
    )


def _snapshot() -> SafeIdentitySnapshot:
    generic_fields = (
        SafeIdentityField("endpoint_or_runtime_id", "prior.runtime"),
        SafeIdentityField("account_or_deployment_digest", DIGEST),
        SafeIdentityField("api_or_route_variant", "prior.variant"),
        SafeIdentityField("environment_or_inventory_digest", DIGEST),
        SafeIdentityField("policy_digest", DIGEST),
    )
    return SafeIdentitySnapshot(
        snapshot_id="prepared.batch-1.prior",
        source_digest="sha256:" + "9" * 64,
        observed_at="2026-08-23T18:00:00+08:00",
        projections=(
            SafeSubjectProjection(
                projection_id="hpc-control",
                logical_subject_id="hpc-primary",
                subject_kind=ExternalQualificationSubjectKind.TARGET,
                status=ExternalSubjectIdentityStatus.RESOLVED,
                component_ids=("openzyme.hpc.ssh", "openzyme.hpc.slurm"),
                safe_fields=(
                    SafeIdentityField("inventory_generation_digest", DIGEST),
                    *generic_fields,
                ),
                missing_fields=(),
            ),
            *(
                SafeSubjectProjection(
                    projection_id=projection_id,
                    logical_subject_id="hpc-primary",
                    subject_kind=ExternalQualificationSubjectKind.TARGET,
                    status=ExternalSubjectIdentityStatus.RESOLVED,
                    component_ids=(component_id,),
                    safe_fields=generic_fields,
                    missing_fields=(),
                )
                for projection_id, component_id in (
                    ("hmmer-hpc", "enzymedesign.hmmer.hpc"),
                    ("vina-hpc", "enzymedesign.vina.hpc"),
                    ("fpocket-hpc", "enzymedesign.fpocket.hpc"),
                )
            ),
        ),
    )


def _hpc_observation() -> HpcQualificationIdentityObservation:
    return HpcQualificationIdentityObservation(
        host_alias="Diannan",
        ssh_port=22222,
        partition="3090",
        environment_digest="sha256:" + "1" * 64,
        inventory_generation_digest="sha256:" + "2" * 64,
        software_versions=(
            ("software.fpocket", "fpocket 4.2.2"),
            ("software.hmmer", "HMMER 3.4"),
            ("software.vina", "AutoDock Vina 1.2.7"),
        ),
        software_image_digests=(
            ("software.fpocket", "sha256:" + "3" * 64),
            ("software.hmmer", "sha256:" + "4" * 64),
            ("software.vina", "sha256:" + "5" * 64),
        ),
        apptainer_version="apptainer version 1.4.2",
    )


def test_workspace_runtime_deployment_evidence_rebinds_hpc_subject() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    identity = _identity(plan, receipt)

    refreshed = augment_prepared_snapshot_with_workspace_runtime(
        snapshot=_snapshot(),
        identity=identity,
        hpc_observation=_hpc_observation(),
        deployment_plan=plan,
        deployment_receipt=receipt,
        source_identity_digest="sha256:" + "a" * 64,
        observed_at=datetime.now(tz=UTC).isoformat(),
    )

    fields = {
        item.field_id: item.value for item in refreshed.projections[0].safe_fields
    }
    assert refreshed.source_digest == "sha256:" + "a" * 64
    assert fields["workspace_runtime_path_digest"] == canonical_sha256_digest(
        {"absolute_path": plan.destination_path}
    )
    assert fields["workspace_runtime_build_digest"] == plan.helper_build_digest
    assert fields["workspace_runtime_deployment_receipt_digest"] == (
        receipt.receipt_digest
    )
    assert fields["policy_digest"] == identity.root_policy_digest
    assert fields["account_or_deployment_digest"] != DIGEST
    projection_fields = {
        item.projection_id: {
            field.field_id: field.value for field in item.safe_fields
        }
        for item in refreshed.projections
    }
    assert projection_fields["hmmer-hpc"]["hmmer_sif_digest"] == (
        "sha256:" + "4" * 64
    )
    assert projection_fields["vina-hpc"]["vina_sif_digest"] == (
        "sha256:" + "5" * 64
    )
    assert projection_fields["fpocket-hpc"]["fpocket_sif_digest"] == (
        "sha256:" + "3" * 64
    )
    validate_hpc_live_bridge_snapshot(refreshed)


def test_live_bridge_preflight_rejects_pre_deployment_snapshot() -> None:
    with pytest.raises(ExternalQualificationError) as captured:
        validate_hpc_live_bridge_snapshot(_snapshot())

    assert captured.value.error_code == (
        "qualification_hpc_live_bridge_field_missing"
    )


def test_workspace_runtime_deployment_evidence_rejects_receipt_drift() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    identity = _identity(plan, receipt)
    other_receipt = WorkspaceRuntimeDeploymentReceipt.create(
        plan_digest=plan.plan_digest,
        authorization_digest="sha256:" + "b" * 64,
        installed_digest=plan.helper_build_digest,
        destination_pre_digest=None,
        native_qualification_digest=receipt.native_qualification_digest,
        rollback_performed=False,
        fallback_performed=False,
    )

    with pytest.raises(ExternalQualificationError) as error:
        augment_prepared_snapshot_with_workspace_runtime(
            snapshot=_snapshot(),
            identity=identity,
            hpc_observation=_hpc_observation(),
            deployment_plan=plan,
            deployment_receipt=other_receipt,
            source_identity_digest="sha256:" + "a" * 64,
            observed_at="2026-08-23T19:00:00+08:00",
        )

    assert error.value.error_code == (
        "qualification_workspace_runtime_deployment_evidence_drift"
    )
