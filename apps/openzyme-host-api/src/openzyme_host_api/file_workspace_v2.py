from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import require_digest
from openzyme_extension_spi import ProjectionContributor
from openzyme_extension_spi import KernelQueryContext
from openzyme_kernel import MountedExtensionSurfaces
from openzyme_kernel import KernelCoreProjectionProvider
from openzyme_kernel import KernelCoreProjectionSource
from openzyme_kernel import assemble_file_workspace_public_v2


class FileWorkspaceV2HostContractError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.mutation_applied = False
        self.fallback_performed = False


@dataclass(frozen=True, slots=True)
class FileWorkspaceV2HostProjection:
    projection: FileWorkspacePublicV2
    query_context: KernelQueryContext
    capability_binding_digest: str
    affordance_snapshot_digest: str

    @property
    def response_headers(self) -> dict[str, str]:
        return {
            "OpenZyme-Workspace-Contract": FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION,
            "OpenZyme-Release-Digest": self.projection.release.release_digest,
            "OpenZyme-Public-Contract-Digest": (
                FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
            ),
            "OpenZyme-Projection-Digest": self.projection.projection_digest,
            "OpenZyme-Capability-Binding-Digest": self.capability_binding_digest,
            "OpenZyme-Affordance-Snapshot-Digest": (self.affordance_snapshot_digest),
        }


@dataclass(frozen=True, slots=True)
class FileWorkspaceV2HostSurface:
    release: LayeredReleaseIdentity
    core_provider: KernelCoreProjectionProvider
    projection_contributors: tuple[ProjectionContributor, ...]
    authorized_projection_contracts: Mapping[str, str]
    activation_digest: str
    runtime_mount_digest: str

    @property
    def release_response_headers(self) -> dict[str, str]:
        """Headers available before a Session projection exists."""

        return {
            "OpenZyme-Workspace-Contract": FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION,
            "OpenZyme-Release-Digest": self.release.release_digest,
            "OpenZyme-Public-Contract-Digest": (
                FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
            ),
        }

    def __post_init__(self) -> None:
        try:
            require_digest(self.activation_digest, field_name="activation_digest")
            require_digest(
                self.runtime_mount_digest,
                field_name="runtime_mount_digest",
            )
        except ValueError as exc:
            raise FileWorkspaceV2HostContractError(
                "file_workspace_v2_mount_identity_invalid",
                "@2 Host surface has a non-canonical activation or mount identity",
                status_code=503,
            ) from exc
        contributors = {
            contributor.section_id: contributor
            for contributor in self.projection_contributors
        }
        if len(contributors) != len(self.projection_contributors):
            raise FileWorkspaceV2HostContractError(
                "file_workspace_v2_projection_runtime_collision",
                "@2 Host surface contains duplicate projection runtimes",
                status_code=503,
            )
        if set(contributors) != set(self.authorized_projection_contracts):
            raise FileWorkspaceV2HostContractError(
                "file_workspace_v2_projection_mount_drift",
                "@2 Host projection runtimes differ from the mounted catalog",
                status_code=503,
            )
        for section_id, contributor in contributors.items():
            if (
                contributor.section_contract_digest
                != self.authorized_projection_contracts[section_id]
            ):
                raise FileWorkspaceV2HostContractError(
                    "file_workspace_v2_projection_contract_drift",
                    "@2 Host projection runtime differs from its mounted contract",
                    status_code=503,
                )

    @classmethod
    def from_mounted_surfaces(
        cls,
        *,
        release: LayeredReleaseIdentity,
        core_provider: KernelCoreProjectionProvider,
        mounted_surfaces: MountedExtensionSurfaces,
    ) -> FileWorkspaceV2HostSurface:
        """Create the delivery surface from one already verified runtime mount."""

        return cls(
            release=release,
            core_provider=core_provider,
            projection_contributors=tuple(
                contributor for _, contributor in mounted_surfaces.projections
            ),
            authorized_projection_contracts={
                section_id: contributor.section_contract_digest
                for section_id, contributor in mounted_surfaces.projections
            },
            activation_digest=mounted_surfaces.activation_digest,
            runtime_mount_digest=mounted_surfaces.mount_digest,
        )

    def inspect(
        self,
        *,
        session_id: str,
        actor_id: str,
        correlation_id: str,
        cursors: Mapping[str, str] | None = None,
    ) -> FileWorkspaceV2HostProjection:
        source = self.core_provider.inspect(
            session_id=session_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        self._require_source_identity(
            source,
            session_id=session_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        projection = assemble_file_workspace_public_v2(
            release=self.release,
            core_payload=source.core_payload,
            query_context=source.context,
            projection_contributors=self.projection_contributors,
            authorized_projection_contracts=self.authorized_projection_contracts,
            cursors=cursors,
        )
        binding_digest, snapshot_digest = _mutation_scope_digests(projection)
        if binding_digest != source.context.capability_binding_digest:
            raise FileWorkspaceV2HostContractError(
                "file_workspace_v2_capability_binding_drift",
                "Core projection capability binding differs from its Kernel query context",
            )
        return FileWorkspaceV2HostProjection(
            projection=projection,
            query_context=source.context,
            capability_binding_digest=binding_digest,
            affordance_snapshot_digest=snapshot_digest,
        )

    def admit_request(
        self,
        *,
        method: str,
        headers: Mapping[str, str],
        session_id: str | None,
        actor_id: str,
        correlation_id: str,
    ) -> FileWorkspaceV2HostProjection | None:
        contract = (headers.get("openzyme-workspace-contract") or "").strip()
        if contract != FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION:
            raise FileWorkspaceV2HostContractError(
                "file_workspace_v2_contract_mismatch",
                "request is not bound to file_workspace_public@2",
            )
        accept = headers.get("accept") or ""
        if FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE not in accept:
            raise FileWorkspaceV2HostContractError(
                "file_workspace_v2_media_type_mismatch",
                "request does not accept the exact file_workspace_public@2 media type",
            )
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        if session_id is None:
            raise FileWorkspaceV2HostContractError(
                "file_workspace_v2_session_scope_required",
                "@2 mutations require one exact Session scope",
            )
        current = self.inspect(
            session_id=session_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        expected = {
            "openzyme-release-digest": self.release.release_digest,
            "openzyme-public-contract-digest": (
                FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
            ),
            "openzyme-projection-digest": current.projection.projection_digest,
            "openzyme-capability-binding-digest": (current.capability_binding_digest),
            "openzyme-affordance-snapshot-digest": (current.affordance_snapshot_digest),
        }
        for header_name, expected_value in expected.items():
            observed = (headers.get(header_name) or "").strip()
            if observed != expected_value:
                raise FileWorkspaceV2HostContractError(
                    "file_workspace_v2_mutation_identity_stale",
                    f"mutation header {header_name!r} is absent or stale",
                )
        return current

    def admit_session_bootstrap_request(
        self,
        *,
        headers: Mapping[str, str],
    ) -> None:
        """Admit pre-Session creation against the active release only.

        Projection, capability-binding and affordance identities do not exist
        until the atomic Kernel bootstrap has created the Session graph.
        """

        contract = (headers.get("openzyme-workspace-contract") or "").strip()
        accept = headers.get("accept") or ""
        if contract != FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION:
            raise FileWorkspaceV2HostContractError(
                "file_workspace_v2_contract_mismatch",
                "request is not bound to file_workspace_public@2",
            )
        if FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE not in accept:
            raise FileWorkspaceV2HostContractError(
                "file_workspace_v2_media_type_mismatch",
                "request does not accept the exact file_workspace_public@2 media type",
            )
        expected = self.release_response_headers
        for header_name in (
            "OpenZyme-Release-Digest",
            "OpenZyme-Public-Contract-Digest",
        ):
            observed = (headers.get(header_name.lower()) or "").strip()
            if observed != expected[header_name]:
                raise FileWorkspaceV2HostContractError(
                    "file_workspace_v2_bootstrap_identity_stale",
                    f"Session bootstrap header {header_name.lower()!r} is absent or stale",
                )

    def _require_source_identity(
        self,
        source: KernelCoreProjectionSource,
        *,
        session_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> None:
        context = source.context
        if (
            context.session_id != session_id
            or context.actor_id != actor_id
            or context.correlation_id != correlation_id
        ):
            raise FileWorkspaceV2HostContractError(
                "file_workspace_v2_query_context_drift",
                "Kernel projection context differs from the authenticated request",
            )
        if context.extension_bundle_digest != self.release.extension_bundle_digest:
            raise FileWorkspaceV2HostContractError(
                "file_workspace_v2_extension_bundle_drift",
                "Kernel projection context differs from the active extension bundle",
            )


def _mutation_scope_digests(
    projection: FileWorkspacePublicV2,
) -> tuple[str, str]:
    core = projection.core.payload
    binding = core.get("capability_binding")
    reflection = core.get("tool_reflection")
    if not isinstance(binding, Mapping) or not isinstance(reflection, Mapping):
        raise FileWorkspaceV2HostContractError(
            "file_workspace_v2_mutation_scope_invalid",
            "@2 projection lacks structured mutation scope identity",
        )
    binding_digest = binding.get("binding_digest")
    reflected_binding = reflection.get("capability_binding_digest")
    snapshot_digest = reflection.get("affordance_snapshot_digest")
    if (
        not isinstance(binding_digest, str)
        or reflected_binding != binding_digest
        or not isinstance(snapshot_digest, str)
    ):
        raise FileWorkspaceV2HostContractError(
            "file_workspace_v2_mutation_scope_invalid",
            "@2 projection binding and affordance identities are inconsistent",
        )
    try:
        require_digest(binding_digest, field_name="capability_binding_digest")
        require_digest(snapshot_digest, field_name="affordance_snapshot_digest")
    except ValueError as exc:
        raise FileWorkspaceV2HostContractError(
            "file_workspace_v2_mutation_scope_invalid",
            "@2 projection mutation scope identity is not canonical",
        ) from exc
    return binding_digest, snapshot_digest


__all__ = [
    "FileWorkspaceV2HostContractError",
    "FileWorkspaceV2HostProjection",
    "FileWorkspaceV2HostSurface",
]
