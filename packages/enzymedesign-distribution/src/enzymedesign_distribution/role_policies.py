from __future__ import annotations

from openzyme_contracts import ToolExposure
from openzyme_contracts import ToolExposureDecision
from openzyme_kernel.affordance import ToolSubjectPolicyAction
from openzyme_kernel.affordance import ToolSubjectPolicyDecision
from openzyme_kernel.catalog import DeclaredToolCatalog
from openzyme_kernel.errors import KernelContractError
from openzyme_kernel.tool_exposure import ToolExposureRolePolicy
from openzyme_kernel.tool_exposure import resolve_tool_exposure_role_policy


ENZYMEDESIGN_RESIDENT_ROLES = (
    "executor",
    "master",
    "reporter",
    "researcher",
)

_COLLABORATION_BASELINE = frozenset(
    {
        "approval.request",
        "capabilities.inspect",
        "protocol.send",
        "task.create",
        "task.delegate",
        "task.finish",
        "task.update",
        "world.inspect",
    }
)
_LOCAL_WORKSPACE_READ = frozenset(
    {"workspace.status", "workspace.fs.list", "workspace.fs.read"}
)
_LOCAL_WORKSPACE_WRITE = frozenset({"workspace.fs.mutate", "workspace.exec"})
_HPC_WORKSPACE = frozenset(
    {
        "hpc.workspace.exec",
        "hpc.workspace.fs.list",
        "hpc.workspace.fs.mutate",
        "hpc.workspace.fs.read",
        "hpc.workspace.inspect",
        "hpc.workspace.request",
        "hpc.workspace.sync_source",
        "hpc.workspace.verify",
    }
)
_REPORTING = frozenset(
    {
        "report.publish",
        "report.render.request",
        "report_draft.get",
        "report_draft.update",
    }
)
_RESEARCH = frozenset(
    {
        "deep_research.start",
        "enzymedesign.interpro.query",
        "enzymedesign.rcsb.query",
        "enzymedesign.sequence.parse",
        "enzymedesign.uniprot.fetch",
    }
)
_SCIENTIFIC_CONTROL = frozenset(
    {
        "scientific.attempt.close",
        "scientific.attempt.inspect",
        "scientific.operation.adopt",
        "scientific.operation.disposition",
        "scientific.selection.begin",
        "scientific.selection.seal",
    }
)
_EXECUTION_ESSENTIALS = frozenset(
    {
        "enzymedesign.alphafold.predict",
        "enzymedesign.docking.preprocess",
        "enzymedesign.fpocket.detect",
        "enzymedesign.hmmer.build",
        "enzymedesign.hmmer.search",
        "enzymedesign.vina.dock",
        "workspace_revision_job.cancel",
        "workspace_revision_job.observe",
        "workspace_revision_job.submit",
    }
)
_ADOPTED_TOOL_NAMES = frozenset(
    _COLLABORATION_BASELINE
    | _LOCAL_WORKSPACE_READ
    | _LOCAL_WORKSPACE_WRITE
    | _HPC_WORKSPACE
    | _REPORTING
    | _RESEARCH
    | _SCIENTIFIC_CONTROL
    | _EXECUTION_ESSENTIALS
)


def enzymedesign_tool_exposure(
    *,
    subject_role: str,
    tool_name: str,
) -> ToolExposure:
    _require_role(subject_role)
    if tool_name not in _ADOPTED_TOOL_NAMES:
        raise KernelContractError(
            "enzymedesign_tool_exposure_catalog_unknown",
            "EnzymeDesign exposure policy has no decision for a catalog tool",
            details={"tool_name": tool_name, "fallback_performed": False},
        )
    if tool_name in _COLLABORATION_BASELINE:
        return ToolExposure.DIRECT
    if subject_role in {"master", "executor"} and tool_name in (
        _LOCAL_WORKSPACE_READ | _LOCAL_WORKSPACE_WRITE
    ):
        return ToolExposure.DIRECT
    if tool_name in _LOCAL_WORKSPACE_READ:
        return ToolExposure.DIRECT
    if subject_role == "researcher" and tool_name in _RESEARCH:
        return ToolExposure.DIRECT
    if subject_role == "executor" and tool_name in (
        _SCIENTIFIC_CONTROL | _EXECUTION_ESSENTIALS
    ):
        return ToolExposure.DIRECT
    if subject_role == "reporter" and tool_name in (
        _REPORTING | {"scientific.attempt.inspect"}
    ):
        return ToolExposure.DIRECT
    if tool_name in _HPC_WORKSPACE and subject_role != "executor":
        return ToolExposure.HIDDEN
    if subject_role in {"executor", "reporter"} and tool_name == "deep_research.start":
        return ToolExposure.HIDDEN
    if subject_role == "executor" and tool_name == "report.publish":
        return ToolExposure.HIDDEN
    return ToolExposure.DEFERRED


def enzymedesign_subject_policy_decisions(
    catalog: DeclaredToolCatalog,
    *,
    subject_role: str,
) -> tuple[ToolSubjectPolicyDecision, ...]:
    _require_catalog(catalog)
    return tuple(
        ToolSubjectPolicyDecision(
            tool_name=entry.contract.tool_name,
            action=(
                ToolSubjectPolicyAction.HIDE
                if enzymedesign_tool_exposure(
                    subject_role=subject_role,
                    tool_name=entry.contract.tool_name,
                )
                is ToolExposure.HIDDEN
                else ToolSubjectPolicyAction.ALLOW
            ),
        )
        for entry in catalog.entries
    )


def enzymedesign_subject_policy_decisions_by_role(
    catalog: DeclaredToolCatalog,
) -> dict[str, tuple[ToolSubjectPolicyDecision, ...]]:
    return {
        role: enzymedesign_subject_policy_decisions(catalog, subject_role=role)
        for role in ENZYMEDESIGN_RESIDENT_ROLES
    }


def enzymedesign_tool_exposure_policies(
    catalog: DeclaredToolCatalog,
    *,
    release_digest: str,
) -> tuple[ToolExposureRolePolicy, ...]:
    _require_catalog(catalog)
    policies = tuple(
        ToolExposureRolePolicy(
            policy_id=f"enzymedesign.exposure.{role}@1",
            distribution_id="enzymedesign",
            release_digest=release_digest,
            subject_role=role,
            decisions=tuple(
                ToolExposureDecision(
                    tool_name=entry.contract.tool_name,
                    exposure=enzymedesign_tool_exposure(
                        subject_role=role,
                        tool_name=entry.contract.tool_name,
                    ),
                    reason_code=f"enzymedesign_{role}_role_policy",
                )
                for entry in catalog.entries
            ),
        )
        for role in ENZYMEDESIGN_RESIDENT_ROLES
    )
    for role in ENZYMEDESIGN_RESIDENT_ROLES:
        resolve_tool_exposure_role_policy(
            policies=policies,
            distribution_id="enzymedesign",
            adopted_release_digest=release_digest,
            subject_role=role,
            catalog=catalog,
        )
    return policies


def _require_catalog(catalog: DeclaredToolCatalog) -> None:
    names = {entry.contract.tool_name for entry in catalog.entries}
    missing = sorted(_ADOPTED_TOOL_NAMES.difference(names))
    unknown = sorted(names.difference(_ADOPTED_TOOL_NAMES))
    if missing or unknown:
        raise KernelContractError(
            "enzymedesign_tool_exposure_catalog_drift",
            "EnzymeDesign declared catalog differs from its exact adopted policy set",
            details={
                "missing_tool_names": missing,
                "unknown_tool_names": unknown,
                "fallback_performed": False,
            },
        )


def _require_role(subject_role: str) -> None:
    if subject_role not in ENZYMEDESIGN_RESIDENT_ROLES:
        raise KernelContractError(
            "enzymedesign_resident_role_policy_missing",
            "EnzymeDesign has no adopted policy for this resident role",
            details={"subject_role": subject_role, "fallback_performed": False},
        )


__all__ = [
    "ENZYMEDESIGN_RESIDENT_ROLES",
    "enzymedesign_subject_policy_decisions",
    "enzymedesign_subject_policy_decisions_by_role",
    "enzymedesign_tool_exposure",
    "enzymedesign_tool_exposure_policies",
]
