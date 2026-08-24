from __future__ import annotations

from collections import Counter

from openzyme_contracts import ToolExposure
from openzyme_contracts import ToolExposureDecision
from openzyme_kernel.affordance import ToolSubjectPolicyAction
from openzyme_kernel.affordance import ToolSubjectPolicyDecision
from openzyme_kernel.catalog import DeclaredToolCatalog
from openzyme_kernel.errors import KernelContractError
from openzyme_kernel.tool_exposure import ToolExposureRolePolicy
from openzyme_kernel.tool_exposure import resolve_tool_exposure_role_policy


STANDARD_RESIDENT_ROLES = ("master", "teammate")
STANDARD_ADOPTED_TOOL_NAMES = (
    "approval.request",
    "capabilities.inspect",
    "protocol.send",
    "task.create",
    "task.delegate",
    "task.finish",
    "task.update",
    "workspace.exec",
    "workspace.fs.list",
    "workspace.fs.mutate",
    "workspace.fs.read",
    "workspace.status",
    "world.inspect",
)


def standard_subject_policy_decisions(
    catalog: DeclaredToolCatalog,
    *,
    subject_role: str,
) -> tuple[ToolSubjectPolicyDecision, ...]:
    """Return one full-catalog execution policy for a supported Standard role."""

    _require_adopted_catalog(catalog)
    _require_supported_role(subject_role)
    return tuple(
        ToolSubjectPolicyDecision(
            tool_name=entry.contract.tool_name,
            action=ToolSubjectPolicyAction.ALLOW,
        )
        for entry in catalog.entries
    )


def standard_subject_policy_decisions_by_role(
    catalog: DeclaredToolCatalog,
) -> dict[str, tuple[ToolSubjectPolicyDecision, ...]]:
    _require_adopted_catalog(catalog)
    return {
        role: standard_subject_policy_decisions(catalog, subject_role=role)
        for role in STANDARD_RESIDENT_ROLES
    }


def standard_tool_exposure_policies(
    catalog: DeclaredToolCatalog,
    *,
    release_digest: str,
) -> tuple[ToolExposureRolePolicy, ...]:
    """Bind Standard's Plugin-free Direct baseline to the exact release.

    Standard declares no long-tail semantic Plugin tools.  Every declared entry
    is therefore an intentional Direct collaboration/workspace verb, rather than
    an implicit visibility default.  Optional vertical tools are absent from the
    catalog instead of being mounted as stubs.
    """

    _require_adopted_catalog(catalog)
    policies = tuple(
        ToolExposureRolePolicy(
            policy_id=f"openzyme.standard.exposure.{role}@1",
            distribution_id="openzyme.standard",
            release_digest=release_digest,
            subject_role=role,
            decisions=tuple(
                ToolExposureDecision(
                    tool_name=entry.contract.tool_name,
                    exposure=ToolExposure.DIRECT,
                    reason_code="standard_direct_collaboration_baseline",
                )
                for entry in catalog.entries
            ),
        )
        for role in STANDARD_RESIDENT_ROLES
    )
    # Startup/preflight validates every exact role rather than relying on the
    # runtime resolver to discover a missing or release-drifted entry later.
    for role in STANDARD_RESIDENT_ROLES:
        resolve_tool_exposure_role_policy(
            policies=policies,
            distribution_id="openzyme.standard",
            adopted_release_digest=release_digest,
            subject_role=role,
            catalog=catalog,
        )
    return policies


def _require_adopted_catalog(catalog: DeclaredToolCatalog) -> None:
    observed_names = tuple(entry.contract.tool_name for entry in catalog.entries)
    observed_counts = Counter(observed_names)
    adopted_names = set(STANDARD_ADOPTED_TOOL_NAMES)
    observed_name_set = set(observed_names)
    missing = sorted(adopted_names.difference(observed_name_set))
    unknown = sorted(observed_name_set.difference(adopted_names))
    duplicate = sorted(name for name, count in observed_counts.items() if count > 1)
    if missing or unknown or duplicate:
        raise KernelContractError(
            "standard_tool_exposure_catalog_drift",
            "OpenZyme Standard declared catalog differs from its exact adopted policy set",
            details={
                "missing_tool_names": missing,
                "unknown_tool_names": unknown,
                "duplicate_tool_names": duplicate,
                "fallback_performed": False,
            },
        )


def _require_supported_role(subject_role: str) -> None:
    if subject_role not in STANDARD_RESIDENT_ROLES:
        raise ValueError(
            "OpenZyme Standard has no adopted exposure policy for role "
            f"{subject_role!r}"
        )


__all__ = [
    "STANDARD_ADOPTED_TOOL_NAMES",
    "STANDARD_RESIDENT_ROLES",
    "standard_subject_policy_decisions",
    "standard_subject_policy_decisions_by_role",
    "standard_tool_exposure_policies",
]
