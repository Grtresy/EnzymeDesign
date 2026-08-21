from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
from typing import Any

from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier

from .activation import ActivatedDistributionComposition
from .errors import KernelContractError


READ_ONLY_DEPLOYMENT_VERIFICATION_SCHEMA_VERSION = (
    "openzyme_read_only_deployment_verification@1"
)
DEPLOYMENT_SURFACE_AUTHORIZATION_SCHEMA_VERSION = (
    "openzyme_deployment_surface_authorization@1"
)


class DeploymentVerificationKind(StrEnum):
    COMPOSITION = "composition"
    CORE_SCHEMA = "core_schema"
    INSTALLED_WHEELS = "installed_wheels"


class DeploymentSurface(StrEnum):
    REPOSITORY_WRITER = "repository_writer"
    HTTP_ROUTE = "http_route"
    WORKER = "worker"
    RUNTIME = "runtime"
    EXTERNAL_EFFECT = "external_effect"


@dataclass(frozen=True, slots=True)
class ReadOnlyDeploymentVerification:
    verification_id: str
    verification_kind: DeploymentVerificationKind
    verifier_id: str
    expected_digest: str
    observed_digest: str
    verified_at: str
    mutation_applied: bool
    effect_certainty: ExternalEffectCertainty
    fallback_performed: bool
    verification_digest: str

    @classmethod
    def create(
        cls,
        *,
        verification_id: str,
        verification_kind: DeploymentVerificationKind,
        verifier_id: str,
        expected_digest: str,
        observed_digest: str,
        verified_at: str,
    ) -> "ReadOnlyDeploymentVerification":
        verification = cls(
            verification_id=verification_id,
            verification_kind=verification_kind,
            verifier_id=verifier_id,
            expected_digest=expected_digest,
            observed_digest=observed_digest,
            verified_at=verified_at,
            mutation_applied=False,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            fallback_performed=False,
            verification_digest="sha256:" + "0" * 64,
        )
        return replace(
            verification,
            verification_digest=canonical_sha256_digest(
                verification.digest_payload()
            ),
        )

    def __post_init__(self) -> None:
        for field_name in ("verification_id", "verifier_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "expected_digest",
            "observed_digest",
            "verification_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if not isinstance(self.verified_at, str) or not self.verified_at:
            raise ValueError("verified_at must be a non-empty instant")
        if (
            self.mutation_applied
            or self.effect_certainty is not ExternalEffectCertainty.NO_EFFECT
            or self.fallback_performed
        ):
            raise ValueError(
                "deployment verification must be read-only, no-effect and no-fallback"
            )
        placeholder = "sha256:" + "0" * 64
        if (
            self.verification_digest != placeholder
            and self.verification_digest
            != canonical_sha256_digest(self.digest_payload())
        ):
            raise ValueError("verification_digest does not match its payload")

    @property
    def succeeded(self) -> bool:
        return self.expected_digest == self.observed_digest

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": READ_ONLY_DEPLOYMENT_VERIFICATION_SCHEMA_VERSION,
            "verification_id": self.verification_id,
            "verification_kind": self.verification_kind.value,
            "verifier_id": self.verifier_id,
            "expected_digest": self.expected_digest,
            "observed_digest": self.observed_digest,
            "verified_at": self.verified_at,
            "mutation_applied": self.mutation_applied,
            "effect_certainty": self.effect_certainty.value,
            "fallback_performed": self.fallback_performed,
        }

    def has_valid_digest(self) -> bool:
        return self.verification_digest == canonical_sha256_digest(
            self.digest_payload()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.digest_payload(),
            "verification_digest": self.verification_digest,
        }


@dataclass(frozen=True, slots=True)
class DeploymentActivationRequest:
    epoch_id: str
    sequence: int
    expected_wheel_set_digest: str
    activated_by_actor_id: str
    activated_at: str
    verifications: tuple[ReadOnlyDeploymentVerification, ...]

    def __post_init__(self) -> None:
        require_identifier(self.epoch_id, field_name="epoch_id")
        require_identifier(
            self.activated_by_actor_id,
            field_name="activated_by_actor_id",
        )
        require_digest(
            self.expected_wheel_set_digest,
            field_name="expected_wheel_set_digest",
        )
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 1
        ):
            raise ValueError("sequence must be a positive integer")
        if not isinstance(self.activated_at, str) or not self.activated_at:
            raise ValueError("activated_at must be a non-empty instant")
        kinds = [item.verification_kind for item in self.verifications]
        if len(set(kinds)) != len(kinds):
            raise ValueError("verifications must have unique verification kinds")
        object.__setattr__(
            self,
            "verifications",
            tuple(sorted(self.verifications, key=lambda item: item.verification_kind)),
        )


@dataclass(frozen=True, slots=True)
class DeploymentSurfaceAuthorization:
    epoch_id: str
    activation_digest: str
    surface: DeploymentSurface
    authorization_digest: str

    @classmethod
    def create(
        cls,
        *,
        epoch: DeploymentActivationEpoch,
        surface: DeploymentSurface,
    ) -> "DeploymentSurfaceAuthorization":
        payload = {
            "schema_version": DEPLOYMENT_SURFACE_AUTHORIZATION_SCHEMA_VERSION,
            "epoch_id": epoch.epoch_id,
            "activation_digest": epoch.activation_digest,
            "surface": surface.value,
        }
        return cls(
            epoch_id=epoch.epoch_id,
            activation_digest=epoch.activation_digest,
            surface=surface,
            authorization_digest=canonical_sha256_digest(payload),
        )

    def __post_init__(self) -> None:
        require_identifier(self.epoch_id, field_name="epoch_id")
        require_digest(self.activation_digest, field_name="activation_digest")
        require_digest(
            self.authorization_digest,
            field_name="authorization_digest",
        )
        if self.authorization_digest != canonical_sha256_digest(self.digest_payload()):
            raise ValueError("surface authorization digest mismatch")

    def digest_payload(self) -> dict[str, str]:
        return {
            "schema_version": DEPLOYMENT_SURFACE_AUTHORIZATION_SCHEMA_VERSION,
            "epoch_id": self.epoch_id,
            "activation_digest": self.activation_digest,
            "surface": self.surface.value,
        }


class DeploymentActivationGate:
    """In-memory startup gate; failed verification never exposes a partial surface."""

    def __init__(self) -> None:
        self._epoch: DeploymentActivationEpoch | None = None

    @property
    def active_epoch(self) -> DeploymentActivationEpoch | None:
        return self._epoch

    def _activate(self, epoch: DeploymentActivationEpoch) -> None:
        if self._epoch is not None:
            raise KernelContractError(
                "deployment_hot_activation_forbidden",
                "an active deployment composition cannot be replaced online",
                details={
                    "active_epoch_id": self._epoch.epoch_id,
                    "requested_epoch_id": epoch.epoch_id,
                },
            )
        if not epoch.has_valid_digest():
            raise KernelContractError(
                "deployment_activation_digest_mismatch",
                "deployment activation epoch has an invalid digest",
                details={"epoch_id": epoch.epoch_id},
            )
        self._epoch = epoch

    def require_active(
        self,
        surface: DeploymentSurface,
    ) -> DeploymentSurfaceAuthorization:
        epoch = self._epoch
        if epoch is None:
            raise KernelContractError(
                "deployment_not_active",
                "deployment composition is not verified and active",
                details={"surface": surface.value},
            )
        return DeploymentSurfaceAuthorization.create(epoch=epoch, surface=surface)

    def validate_authorization(
        self,
        authorization: DeploymentSurfaceAuthorization,
        *,
        surface: DeploymentSurface,
    ) -> DeploymentActivationEpoch:
        epoch = self._epoch
        if (
            epoch is None
            or authorization.surface is not surface
            or authorization.epoch_id != epoch.epoch_id
            or authorization.activation_digest != epoch.activation_digest
            or authorization.authorization_digest
            != canonical_sha256_digest(authorization.digest_payload())
        ):
            raise KernelContractError(
                "deployment_surface_authorization_stale",
                "surface authorization does not belong to the active deployment epoch",
                details={"surface": surface.value},
            )
        return epoch


@dataclass(frozen=True, slots=True)
class DeploymentActivationCoordinator:
    gate: DeploymentActivationGate

    def activate(
        self,
        *,
        composition: ActivatedDistributionComposition,
        release_identity: LayeredReleaseIdentity,
        request: DeploymentActivationRequest,
    ) -> DeploymentActivationEpoch:
        if self.gate.active_epoch is not None:
            raise KernelContractError(
                "deployment_hot_activation_forbidden",
                "a new composition epoch requires quiescence and offline activation",
                details={"requested_epoch_id": request.epoch_id},
            )
        self._verify_release_identity(composition, release_identity)
        verifications = self._verify_current_verifications(
            composition=composition,
            release_identity=release_identity,
            expected_wheel_set_digest=request.expected_wheel_set_digest,
            verifications=request.verifications,
        )

        epoch = DeploymentActivationEpoch.create(
            epoch_id=request.epoch_id,
            sequence=request.sequence,
            distribution_id=composition.distribution_id,
            kernel_manifest_digest=composition.kernel_identity.manifest_digest,
            distribution_manifest_digest=composition.distribution_manifest_digest,
            composition_document_digest=composition.composition_document_digest,
            composition_activation_digest=composition.activation_digest,
            driver_bundle_digest=composition.driver_bundle_digest,
            http_route_catalog_digest=composition.http_route_catalog.catalog_digest,
            contribution_catalogs_digest=(
                composition.contribution_catalogs.catalogs_digest
            ),
            release_identity=release_identity,
            schema_verification_digest=verifications[
                DeploymentVerificationKind.CORE_SCHEMA
            ].verification_digest,
            wheel_verification_digest=verifications[
                DeploymentVerificationKind.INSTALLED_WHEELS
            ].verification_digest,
            activated_by_actor_id=request.activated_by_actor_id,
            activated_at=request.activated_at,
        )
        self.gate._activate(epoch)
        return epoch

    def reactivate_persisted(
        self,
        *,
        composition: ActivatedDistributionComposition,
        persisted_epoch: DeploymentActivationEpoch,
        expected_wheel_set_digest: str,
        verifications: tuple[ReadOnlyDeploymentVerification, ...],
    ) -> DeploymentActivationEpoch:
        """Open a process-local gate only after re-verifying one persisted epoch.

        Restart never creates a replacement epoch and never treats the persisted
        receipt as current observation.  The current process supplies fresh,
        read-only composition/schema/wheel proofs; the immutable stored epoch is
        then checked against the exact selected composition before any surface is
        authorized.
        """

        if self.gate.active_epoch is not None:
            raise KernelContractError(
                "deployment_hot_activation_forbidden",
                "a persisted deployment epoch cannot replace an active epoch online",
                details={"requested_epoch_id": persisted_epoch.epoch_id},
            )
        if not persisted_epoch.has_valid_digest():
            raise KernelContractError(
                "deployment_activation_digest_mismatch",
                "persisted deployment activation epoch has an invalid digest",
                details={"epoch_id": persisted_epoch.epoch_id},
            )
        release_identity = persisted_epoch.release_identity
        self._verify_release_identity(composition, release_identity)
        self._verify_current_verifications(
            composition=composition,
            release_identity=release_identity,
            expected_wheel_set_digest=expected_wheel_set_digest,
            verifications=verifications,
        )
        expected_epoch = DeploymentActivationEpoch.create(
            epoch_id=persisted_epoch.epoch_id,
            sequence=persisted_epoch.sequence,
            distribution_id=composition.distribution_id,
            kernel_manifest_digest=composition.kernel_identity.manifest_digest,
            distribution_manifest_digest=composition.distribution_manifest_digest,
            composition_document_digest=composition.composition_document_digest,
            composition_activation_digest=composition.activation_digest,
            driver_bundle_digest=composition.driver_bundle_digest,
            http_route_catalog_digest=composition.http_route_catalog.catalog_digest,
            contribution_catalogs_digest=(
                composition.contribution_catalogs.catalogs_digest
            ),
            release_identity=release_identity,
            schema_verification_digest=persisted_epoch.schema_verification_digest,
            wheel_verification_digest=persisted_epoch.wheel_verification_digest,
            activated_by_actor_id=persisted_epoch.activated_by_actor_id,
            activated_at=persisted_epoch.activated_at,
        )
        if expected_epoch != persisted_epoch:
            raise KernelContractError(
                "deployment_persisted_epoch_drift",
                "persisted epoch does not bind the selected composition",
                details={
                    "epoch_id": persisted_epoch.epoch_id,
                    "expected_activation_digest": expected_epoch.activation_digest,
                    "observed_activation_digest": persisted_epoch.activation_digest,
                },
            )
        self.gate._activate(persisted_epoch)
        return persisted_epoch

    @staticmethod
    def _verify_current_verifications(
        *,
        composition: ActivatedDistributionComposition,
        release_identity: LayeredReleaseIdentity,
        expected_wheel_set_digest: str,
        verifications: tuple[ReadOnlyDeploymentVerification, ...],
    ) -> dict[DeploymentVerificationKind, ReadOnlyDeploymentVerification]:
        by_kind = {item.verification_kind: item for item in verifications}
        expected_by_kind = {
            DeploymentVerificationKind.COMPOSITION: composition.activation_digest,
            DeploymentVerificationKind.CORE_SCHEMA: release_identity.core_schema_digest,
            DeploymentVerificationKind.INSTALLED_WHEELS: expected_wheel_set_digest,
        }
        if set(by_kind) != set(expected_by_kind):
            raise KernelContractError(
                "deployment_verification_incomplete",
                "deployment activation requires composition, schema and wheel proofs",
                details={
                    "missing_kinds": sorted(
                        kind.value for kind in set(expected_by_kind) - set(by_kind)
                    ),
                    "unexpected_kinds": sorted(
                        kind.value for kind in set(by_kind) - set(expected_by_kind)
                    ),
                },
            )
        for kind, expected_digest in expected_by_kind.items():
            verification = by_kind[kind]
            if (
                not verification.has_valid_digest()
                or verification.expected_digest != expected_digest
                or not verification.succeeded
            ):
                raise KernelContractError(
                    "deployment_verification_failed",
                    "read-only deployment verification did not prove the selected identity",
                    details={
                        "verification_kind": kind.value,
                        "expected_digest": expected_digest,
                        "observed_digest": verification.observed_digest,
                    },
                )
        return by_kind

    @staticmethod
    def _verify_release_identity(
        composition: ActivatedDistributionComposition,
        release_identity: LayeredReleaseIdentity,
    ) -> None:
        workspace_backends = tuple(
            binding
            for binding in composition.adapters
            if binding.selection.slot_id == "workspace.backend"
        )
        workspace_backend_digest = (
            workspace_backends[0].manifest.manifest_digest
            if len(workspace_backends) == 1
            else None
        )
        mismatches = {
            "kernel_contract_digest": (
                release_identity.kernel_contract_digest
                != composition.kernel_identity.contract_digest
            ),
            "adapter_bundle_digest": (
                release_identity.adapter_bundle_digest
                != composition.adapter_bundle_digest
            ),
            "extension_bundle_digest": (
                release_identity.extension_bundle_digest
                != composition.plugins.extension_bundle_digest
            ),
            "declared_tool_catalog_digest": (
                release_identity.declared_tool_catalog_digest
                != composition.declared_tool_catalog.catalog_digest
            ),
            "route_catalog_digest": (
                release_identity.route_catalog_digest
                != composition.route_catalog.catalog_digest
            ),
            "projection_catalog_digest": (
                release_identity.projection_catalog_digest
                != composition.contribution_catalogs.projection.catalog_digest
            ),
            "migration_catalog_digest": (
                release_identity.migration_catalog_digest
                != composition.contribution_catalogs.migration.catalog_digest
            ),
            "workspace_backend_digest": (
                workspace_backend_digest is None
                or release_identity.workspace_backend_digest
                != workspace_backend_digest
            ),
        }
        drifted = sorted(field for field, mismatch in mismatches.items() if mismatch)
        if drifted:
            raise KernelContractError(
                "deployment_release_identity_drift",
                "release identity does not match the activated composition catalogs",
                details={"drifted_fields": drifted},
            )


__all__ = [
    "DEPLOYMENT_SURFACE_AUTHORIZATION_SCHEMA_VERSION",
    "READ_ONLY_DEPLOYMENT_VERIFICATION_SCHEMA_VERSION",
    "DeploymentActivationCoordinator",
    "DeploymentActivationGate",
    "DeploymentActivationRequest",
    "DeploymentSurface",
    "DeploymentSurfaceAuthorization",
    "DeploymentVerificationKind",
    "ReadOnlyDeploymentVerification",
]
