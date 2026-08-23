from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalSubjectIdentityStatus
from openzyme_contracts import SafeIdentityField
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_hpc import HpcQualificationIdentityObservation
from openzyme_hpc_ssh import DIANNAN_WORKSPACE_RUNTIME_PARENT
from openzyme_hpc_ssh import DIANNAN_WORKSPACE_RUNTIME_PATH
from openzyme_hpc_ssh import DIANNAN_WORKSPACE_RUNTIME_POLICY_ID
from openzyme_hpc_ssh import SshWorkspaceRuntimeQualificationIdentity
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentPlan
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentReceipt

from .qualification_planning import SafeIdentitySnapshot


_GENERIC_CLOSURE_FIELDS = {
    "endpoint_or_runtime_id",
    "account_or_deployment_digest",
    "api_or_route_variant",
    "environment_or_inventory_digest",
    "policy_digest",
}

_HPC_SCIENTIFIC_PROJECTIONS: Mapping[str, tuple[str, str, str, str]] = {
    "hmmer-hpc": (
        "software.hmmer",
        "hmmer_software_fact",
        "hmmer_sif_digest",
        "hmmer_version",
    ),
    "vina-hpc": (
        "software.vina",
        "vina_software_fact",
        "vina_sif_digest",
        "vina_version",
    ),
    "fpocket-hpc": (
        "software.fpocket",
        "fpocket_software_fact",
        "fpocket_sif_digest",
        "fpocket_version",
    ),
}

_HPC_CONTROL_LIVE_BRIDGE_FIELDS = (
    "workspace_runtime_policy_id",
    "workspace_runtime_version",
    "workspace_runtime_build_digest",
    "workspace_runtime_root_policy_digest",
    "workspace_runtime_principal_identity_digest",
    "workspace_runtime_deployment_plan_digest",
    "workspace_runtime_deployment_receipt_digest",
    "workspace_runtime_native_qualification_digest",
    "workspace_runtime_file_owner",
    "workspace_runtime_file_group",
    "workspace_runtime_file_mode",
    "workspace_runtime_observation_digest",
)


def validate_hpc_live_bridge_snapshot(snapshot: SafeIdentitySnapshot) -> None:
    """Reject authorizable-looking evidence that cannot build the exact HPC bridge."""

    projections = {item.projection_id: item for item in snapshot.projections}
    required = {
        "hpc-control": _HPC_CONTROL_LIVE_BRIDGE_FIELDS,
        **{
            projection_id: (image_digest_field, version_field)
            for projection_id, (_, _, image_digest_field, version_field) in (
                _HPC_SCIENTIFIC_PROJECTIONS.items()
            )
        },
    }
    for projection_id, field_ids in required.items():
        projection = projections.get(projection_id)
        if projection is None:
            raise ExternalQualificationError(
                "qualification_hpc_live_bridge_projection_missing",
                "prepared snapshot lacks one exact HPC live-bridge projection",
            )
        values = {item.field_id: item.value for item in projection.safe_fields}
        if any(not values.get(field_id) for field_id in field_ids):
            raise ExternalQualificationError(
                "qualification_hpc_live_bridge_field_missing",
                "prepared snapshot lacks one exact HPC live-bridge field",
            )
        for field_id in field_ids:
            if field_id.endswith("_digest"):
                require_digest(values[field_id], field_name=field_id)


def workspace_runtime_safe_identity_fields(
    identity: SshWorkspaceRuntimeQualificationIdentity,
) -> tuple[SafeIdentityField, ...]:
    values = {
        "workspace_runtime_path_digest": canonical_sha256_digest(
            {"absolute_path": identity.helper_path}
        ),
        "workspace_runtime_parent_digest": canonical_sha256_digest(
            {"absolute_path": identity.workspace_parent}
        ),
        "workspace_runtime_policy_id": identity.policy_id,
        "workspace_runtime_version": identity.helper_version,
        "workspace_runtime_build_digest": identity.helper_build_digest,
        "workspace_runtime_root_policy_digest": identity.root_policy_digest,
        "workspace_runtime_principal_identity_digest": (
            identity.principal_identity_digest
        ),
        "workspace_runtime_deployment_plan_digest": (
            identity.deployment_plan_digest
        ),
        "workspace_runtime_deployment_receipt_digest": (
            identity.deployment_receipt_digest
        ),
        "workspace_runtime_native_qualification_digest": (
            identity.native_qualification_digest
        ),
        "workspace_runtime_file_owner": identity.file_owner,
        "workspace_runtime_file_group": identity.file_group,
        "workspace_runtime_file_mode": identity.file_mode,
        "workspace_runtime_observation_digest": identity.observation_digest,
    }
    return tuple(
        SafeIdentityField(field_id, value)
        for field_id, value in sorted(values.items())
    )


def augment_prepared_snapshot_with_workspace_runtime(
    *,
    snapshot: SafeIdentitySnapshot,
    identity: SshWorkspaceRuntimeQualificationIdentity,
    hpc_observation: HpcQualificationIdentityObservation,
    deployment_plan: WorkspaceRuntimeDeploymentPlan,
    deployment_receipt: WorkspaceRuntimeDeploymentReceipt,
    source_identity_digest: str,
    observed_at: str,
) -> SafeIdentitySnapshot:
    """Adopt independently verified deployment evidence without issuing qualification."""

    require_digest(source_identity_digest, field_name="source_identity_digest")
    if (
        hpc_observation.host_alias != "Diannan"
        or hpc_observation.partition != "3090"
        or identity.helper_path != DIANNAN_WORKSPACE_RUNTIME_PATH
        or identity.workspace_parent != DIANNAN_WORKSPACE_RUNTIME_PARENT
        or identity.policy_id != DIANNAN_WORKSPACE_RUNTIME_POLICY_ID
        or deployment_plan.destination_path != identity.helper_path
        or deployment_plan.workspace_parent != identity.workspace_parent
        or deployment_plan.plan_digest != identity.deployment_plan_digest
        or deployment_plan.helper_build_digest != identity.helper_build_digest
        or deployment_receipt.plan_digest != deployment_plan.plan_digest
        or deployment_receipt.receipt_digest != identity.deployment_receipt_digest
        or deployment_receipt.installed_digest != identity.helper_build_digest
        or deployment_receipt.native_qualification_digest
        != identity.native_qualification_digest
        or deployment_receipt.rollback_performed
        or deployment_receipt.fallback_performed
    ):
        raise ExternalQualificationError(
            "qualification_workspace_runtime_deployment_evidence_drift",
            "workspace runtime observation differs from exact deployment evidence",
        )
    projections_by_id = {item.projection_id: item for item in snapshot.projections}
    if set(_HPC_SCIENTIFIC_PROJECTIONS).difference(projections_by_id):
        raise ExternalQualificationError(
            "qualification_hpc_scientific_projection_missing",
            "prepared snapshot lacks one or more exact HPC scientific projections",
        )
    scientific_projections = {}
    for projection_id, (
        software_id,
        software_fact_field,
        image_digest_field,
        version_field,
    ) in _HPC_SCIENTIFIC_PROJECTIONS.items():
        projection = projections_by_id[projection_id]
        domain_fields = {
            item.field_id: item.value for item in projection.safe_fields
        }
        domain_fields.update(
            {
                "hpc_inventory_generation_digest": (
                    hpc_observation.inventory_generation_digest
                ),
                software_fact_field: canonical_sha256_digest(
                    {
                        "software": software_id,
                        "version": hpc_observation.software_version(software_id),
                        "image_digest": hpc_observation.software_image_digest(
                            software_id
                        ),
                        "runtime": hpc_observation.apptainer_version,
                        "environment": hpc_observation.environment_digest,
                    }
                ),
                image_digest_field: hpc_observation.software_image_digest(software_id),
                version_field: hpc_observation.software_version(software_id),
                "environment_or_inventory_digest": (
                    hpc_observation.environment_digest
                ),
            }
        )
        scientific_projections[projection_id] = replace(
            projection,
            safe_fields=tuple(
                SafeIdentityField(field_id, value)
                for field_id, value in sorted(domain_fields.items())
            ),
        )
    matches = tuple(
        item for item in snapshot.projections if item.projection_id == "hpc-control"
    )
    if len(matches) != 1:
        raise ExternalQualificationError(
            "qualification_workspace_runtime_projection_missing",
            "prepared snapshot lacks the exact HPC control projection",
        )
    projection = matches[0]
    if (
        projection.logical_subject_id != "hpc-primary"
        or projection.status is not ExternalSubjectIdentityStatus.RESOLVED
        or projection.missing_fields
        or set(projection.component_ids)
        != {"openzyme.hpc.ssh", "openzyme.hpc.slurm"}
    ):
        raise ExternalQualificationError(
            "qualification_workspace_runtime_projection_drift",
            "HPC control projection is not one resolved exact subject",
        )
    domain_fields = {
        item.field_id: item.value
        for item in projection.safe_fields
        if item.field_id not in _GENERIC_CLOSURE_FIELDS
    }
    domain_fields["inventory_generation_digest"] = (
        hpc_observation.inventory_generation_digest
    )
    for item in workspace_runtime_safe_identity_fields(identity):
        existing = domain_fields.get(item.field_id)
        if existing is not None and existing != item.value:
            raise ExternalQualificationError(
                "qualification_workspace_runtime_subject_identity_drift",
                "prepared HPC subject already binds a different helper identity",
            )
        domain_fields[item.field_id] = item.value
    closure = {
        "schema_version": "enzymedesign_hpc_workspace_runtime_subject_closure@1",
        "projection_id": projection.projection_id,
        "logical_subject_id": projection.logical_subject_id,
        "component_ids": list(projection.component_ids),
        "domain_fields": dict(sorted(domain_fields.items())),
        "prior_snapshot_source_digest": snapshot.source_digest,
        "deployment_plan_digest": deployment_plan.plan_digest,
        "deployment_receipt_digest": deployment_receipt.receipt_digest,
        "observation_digest": identity.observation_digest,
    }
    domain_fields.update(
        {
            "endpoint_or_runtime_id": (
                "qualification.hpc-control.workspace-runtime.v1"
            ),
            "account_or_deployment_digest": canonical_sha256_digest(
                {**closure, "closure_kind": "account-or-deployment"}
            ),
            "api_or_route_variant": (
                "qualification.hpc-control.workspace-runtime-v1"
            ),
            "environment_or_inventory_digest": canonical_sha256_digest(
                {**closure, "closure_kind": "environment-or-inventory"}
            ),
            "policy_digest": identity.root_policy_digest,
        }
    )
    updated = replace(
        projection,
        safe_fields=tuple(
            SafeIdentityField(field_id, value)
            for field_id, value in sorted(domain_fields.items())
        ),
    )
    projections = tuple(
        updated
        if item.projection_id == updated.projection_id
        else scientific_projections.get(item.projection_id, item)
        for item in snapshot.projections
    )
    snapshot_payload = {
        "source_identity_digest": source_identity_digest,
        "prior_snapshot_id": snapshot.snapshot_id,
        "deployment_receipt_digest": deployment_receipt.receipt_digest,
        "workspace_runtime_observation_digest": identity.observation_digest,
        "hpc_environment_digest": hpc_observation.environment_digest,
        "hpc_inventory_generation_digest": (
            hpc_observation.inventory_generation_digest
        ),
        "projections": [
            {
                "projection_id": item.projection_id,
                "safe_fields": [field.to_dict() for field in item.safe_fields],
            }
            for item in projections
        ],
    }
    return SafeIdentitySnapshot(
        snapshot_id=(
            "prepared.batch-1.workspace-runtime."
            + canonical_sha256_digest(snapshot_payload)[7:23]
        ),
        source_digest=source_identity_digest,
        observed_at=observed_at,
        projections=projections,
    )


__all__ = [
    "augment_prepared_snapshot_with_workspace_runtime",
    "validate_hpc_live_bridge_snapshot",
    "workspace_runtime_safe_identity_fields",
]
