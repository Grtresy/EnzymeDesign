from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from typing import Any

from .identity import canonical_sha256_digest
from .identity import require_digest
from .identity import require_identifier


LAYERED_RELEASE_IDENTITY_SCHEMA_VERSION = "openzyme_layered_release_identity@1"
DEPLOYMENT_ACTIVATION_EPOCH_SCHEMA_VERSION = "openzyme_deployment_activation_epoch@1"
SESSION_COMPOSITION_PIN_SCHEMA_VERSION = "openzyme_session_composition_pin@1"


@dataclass(frozen=True, slots=True)
class LayeredReleaseIdentity:
    kernel_contract_digest: str
    core_schema_digest: str
    adapter_bundle_digest: str
    extension_bundle_digest: str
    declared_tool_catalog_digest: str
    route_catalog_digest: str
    projection_catalog_digest: str
    migration_catalog_digest: str
    workspace_backend_digest: str
    host_build_digest: str
    client_build_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "kernel_contract_digest",
            "core_schema_digest",
            "adapter_bundle_digest",
            "extension_bundle_digest",
            "declared_tool_catalog_digest",
            "route_catalog_digest",
            "projection_catalog_digest",
            "migration_catalog_digest",
            "workspace_backend_digest",
            "host_build_digest",
            "client_build_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LAYERED_RELEASE_IDENTITY_SCHEMA_VERSION,
            "kernel_contract_digest": self.kernel_contract_digest,
            "core_schema_digest": self.core_schema_digest,
            "adapter_bundle_digest": self.adapter_bundle_digest,
            "extension_bundle_digest": self.extension_bundle_digest,
            "declared_tool_catalog_digest": self.declared_tool_catalog_digest,
            "route_catalog_digest": self.route_catalog_digest,
            "projection_catalog_digest": self.projection_catalog_digest,
            "migration_catalog_digest": self.migration_catalog_digest,
            "workspace_backend_digest": self.workspace_backend_digest,
            "host_build_digest": self.host_build_digest,
            "client_build_digest": self.client_build_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> "LayeredReleaseIdentity":
        expected = {
            "schema_version",
            "kernel_contract_digest",
            "core_schema_digest",
            "adapter_bundle_digest",
            "extension_bundle_digest",
            "declared_tool_catalog_digest",
            "route_catalog_digest",
            "projection_catalog_digest",
            "migration_catalog_digest",
            "workspace_backend_digest",
            "host_build_digest",
            "client_build_digest",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("layered release identity fields are closed")
        if value["schema_version"] != LAYERED_RELEASE_IDENTITY_SCHEMA_VERSION:
            raise ValueError("unsupported layered release identity schema")
        return cls(
            kernel_contract_digest=str(value["kernel_contract_digest"]),
            core_schema_digest=str(value["core_schema_digest"]),
            adapter_bundle_digest=str(value["adapter_bundle_digest"]),
            extension_bundle_digest=str(value["extension_bundle_digest"]),
            declared_tool_catalog_digest=str(
                value["declared_tool_catalog_digest"]
            ),
            route_catalog_digest=str(value["route_catalog_digest"]),
            projection_catalog_digest=str(value["projection_catalog_digest"]),
            migration_catalog_digest=str(value["migration_catalog_digest"]),
            workspace_backend_digest=str(value["workspace_backend_digest"]),
            host_build_digest=str(value["host_build_digest"]),
            client_build_digest=str(value["client_build_digest"]),
        )

    @property
    def release_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    @property
    def host_client_epoch_digest(self) -> str:
        """Compatibility identity for the exact delivery pair, not a capability set."""

        return canonical_sha256_digest(
            {
                "host_build_digest": self.host_build_digest,
                "client_build_digest": self.client_build_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class DeploymentActivationEpoch:
    """One immutable deployment composition admitted after read-only verification."""

    epoch_id: str
    sequence: int
    distribution_id: str
    kernel_manifest_digest: str
    distribution_manifest_digest: str
    composition_document_digest: str
    composition_activation_digest: str
    driver_bundle_digest: str
    http_route_catalog_digest: str
    contribution_catalogs_digest: str
    release_identity: LayeredReleaseIdentity
    schema_verification_digest: str
    wheel_verification_digest: str
    activated_by_actor_id: str
    activated_at: str
    composition_bundle_digest: str
    activation_digest: str

    @classmethod
    def create(
        cls,
        *,
        epoch_id: str,
        sequence: int,
        distribution_id: str,
        kernel_manifest_digest: str,
        distribution_manifest_digest: str,
        composition_document_digest: str,
        composition_activation_digest: str,
        driver_bundle_digest: str,
        http_route_catalog_digest: str,
        contribution_catalogs_digest: str,
        release_identity: LayeredReleaseIdentity,
        schema_verification_digest: str,
        wheel_verification_digest: str,
        activated_by_actor_id: str,
        activated_at: str,
    ) -> "DeploymentActivationEpoch":
        provisional = cls(
            epoch_id=epoch_id,
            sequence=sequence,
            distribution_id=distribution_id,
            kernel_manifest_digest=kernel_manifest_digest,
            distribution_manifest_digest=distribution_manifest_digest,
            composition_document_digest=composition_document_digest,
            composition_activation_digest=composition_activation_digest,
            driver_bundle_digest=driver_bundle_digest,
            http_route_catalog_digest=http_route_catalog_digest,
            contribution_catalogs_digest=contribution_catalogs_digest,
            release_identity=release_identity,
            schema_verification_digest=schema_verification_digest,
            wheel_verification_digest=wheel_verification_digest,
            activated_by_actor_id=activated_by_actor_id,
            activated_at=activated_at,
            composition_bundle_digest="sha256:" + "0" * 64,
            activation_digest="sha256:" + "0" * 64,
        )
        with_bundle = replace(
            provisional,
            composition_bundle_digest=canonical_sha256_digest(
                provisional.composition_bundle_payload()
            ),
        )
        return replace(
            with_bundle,
            activation_digest=canonical_sha256_digest(with_bundle.digest_payload()),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "epoch_id",
            "distribution_id",
            "activated_by_actor_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            raise ValueError("sequence must be a positive integer")
        if self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        if not isinstance(self.activated_at, str) or not self.activated_at:
            raise ValueError("activated_at must be a non-empty instant")
        for field_name in (
            "kernel_manifest_digest",
            "distribution_manifest_digest",
            "composition_document_digest",
            "composition_activation_digest",
            "driver_bundle_digest",
            "http_route_catalog_digest",
            "contribution_catalogs_digest",
            "schema_verification_digest",
            "wheel_verification_digest",
            "composition_bundle_digest",
            "activation_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        placeholder = "sha256:" + "0" * 64
        if (
            self.composition_bundle_digest != placeholder
            and self.composition_bundle_digest
            != canonical_sha256_digest(self.composition_bundle_payload())
        ):
            raise ValueError("composition_bundle_digest does not match its payload")
        if (
            self.activation_digest != placeholder
            and self.activation_digest
            != canonical_sha256_digest(self.digest_payload())
        ):
            raise ValueError("activation_digest does not match its payload")

    def composition_bundle_payload(self) -> dict[str, Any]:
        return {
            "distribution_id": self.distribution_id,
            "kernel_manifest_digest": self.kernel_manifest_digest,
            "distribution_manifest_digest": self.distribution_manifest_digest,
            "composition_document_digest": self.composition_document_digest,
            "composition_activation_digest": self.composition_activation_digest,
            "driver_bundle_digest": self.driver_bundle_digest,
            "http_route_catalog_digest": self.http_route_catalog_digest,
            "contribution_catalogs_digest": self.contribution_catalogs_digest,
            "release_identity": self.release_identity.to_dict(),
        }

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": DEPLOYMENT_ACTIVATION_EPOCH_SCHEMA_VERSION,
            "epoch_id": self.epoch_id,
            "sequence": self.sequence,
            "composition_bundle_digest": self.composition_bundle_digest,
            "schema_verification_digest": self.schema_verification_digest,
            "wheel_verification_digest": self.wheel_verification_digest,
            "activated_by_actor_id": self.activated_by_actor_id,
            "activated_at": self.activated_at,
        }

    def has_valid_digest(self) -> bool:
        return (
            self.composition_bundle_digest
            == canonical_sha256_digest(self.composition_bundle_payload())
            and self.activation_digest
            == canonical_sha256_digest(self.digest_payload())
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.digest_payload(), "activation_digest": self.activation_digest}


@dataclass(frozen=True, slots=True)
class SessionCompositionPin:
    """Exact immutable composition identity atomically created with a Session."""

    pin_id: str
    session_id: str
    deployment_epoch_id: str
    deployment_activation_digest: str
    distribution_id: str
    composition_bundle_digest: str
    release_identity: LayeredReleaseIdentity
    driver_bundle_digest: str
    http_route_catalog_digest: str
    contribution_catalogs_digest: str
    initial_capability_binding_id: str
    initial_capability_binding_revision: int
    initial_capability_binding_digest: str
    created_by_actor_id: str
    created_at: str
    pin_digest: str

    @classmethod
    def create(
        cls,
        *,
        pin_id: str,
        session_id: str,
        deployment_epoch: DeploymentActivationEpoch,
        initial_capability_binding_id: str,
        initial_capability_binding_revision: int,
        initial_capability_binding_digest: str,
        created_by_actor_id: str,
        created_at: str,
    ) -> "SessionCompositionPin":
        pin = cls(
            pin_id=pin_id,
            session_id=session_id,
            deployment_epoch_id=deployment_epoch.epoch_id,
            deployment_activation_digest=deployment_epoch.activation_digest,
            distribution_id=deployment_epoch.distribution_id,
            composition_bundle_digest=deployment_epoch.composition_bundle_digest,
            release_identity=deployment_epoch.release_identity,
            driver_bundle_digest=deployment_epoch.driver_bundle_digest,
            http_route_catalog_digest=deployment_epoch.http_route_catalog_digest,
            contribution_catalogs_digest=deployment_epoch.contribution_catalogs_digest,
            initial_capability_binding_id=initial_capability_binding_id,
            initial_capability_binding_revision=initial_capability_binding_revision,
            initial_capability_binding_digest=initial_capability_binding_digest,
            created_by_actor_id=created_by_actor_id,
            created_at=created_at,
            pin_digest="sha256:" + "0" * 64,
        )
        return replace(pin, pin_digest=canonical_sha256_digest(pin.digest_payload()))

    def __post_init__(self) -> None:
        for field_name in (
            "pin_id",
            "session_id",
            "deployment_epoch_id",
            "distribution_id",
            "initial_capability_binding_id",
            "created_by_actor_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if (
            not isinstance(self.initial_capability_binding_revision, int)
            or isinstance(self.initial_capability_binding_revision, bool)
            or self.initial_capability_binding_revision != 1
        ):
            raise ValueError("initial_capability_binding_revision must be exactly 1")
        if not isinstance(self.created_at, str) or not self.created_at:
            raise ValueError("created_at must be a non-empty instant")
        for field_name in (
            "deployment_activation_digest",
            "composition_bundle_digest",
            "driver_bundle_digest",
            "http_route_catalog_digest",
            "contribution_catalogs_digest",
            "initial_capability_binding_digest",
            "pin_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        placeholder = "sha256:" + "0" * 64
        if (
            self.pin_digest != placeholder
            and self.pin_digest != canonical_sha256_digest(self.digest_payload())
        ):
            raise ValueError("pin_digest does not match its payload")

    @property
    def host_client_epoch_digest(self) -> str:
        return self.release_identity.host_client_epoch_digest

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SESSION_COMPOSITION_PIN_SCHEMA_VERSION,
            "pin_id": self.pin_id,
            "session_id": self.session_id,
            "deployment_epoch_id": self.deployment_epoch_id,
            "deployment_activation_digest": self.deployment_activation_digest,
            "distribution_id": self.distribution_id,
            "composition_bundle_digest": self.composition_bundle_digest,
            "release_identity": self.release_identity.to_dict(),
            "driver_bundle_digest": self.driver_bundle_digest,
            "http_route_catalog_digest": self.http_route_catalog_digest,
            "contribution_catalogs_digest": self.contribution_catalogs_digest,
            "initial_capability_binding_id": self.initial_capability_binding_id,
            "initial_capability_binding_revision": (
                self.initial_capability_binding_revision
            ),
            "initial_capability_binding_digest": (
                self.initial_capability_binding_digest
            ),
            "host_client_epoch_digest": self.host_client_epoch_digest,
            "created_by_actor_id": self.created_by_actor_id,
            "created_at": self.created_at,
        }

    def has_valid_digest(self) -> bool:
        return self.pin_digest == canonical_sha256_digest(self.digest_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.digest_payload(), "pin_digest": self.pin_digest}

    @classmethod
    def from_dict(cls, value: object) -> "SessionCompositionPin":
        expected = {
            "schema_version",
            "pin_id",
            "session_id",
            "deployment_epoch_id",
            "deployment_activation_digest",
            "distribution_id",
            "composition_bundle_digest",
            "release_identity",
            "driver_bundle_digest",
            "http_route_catalog_digest",
            "contribution_catalogs_digest",
            "initial_capability_binding_id",
            "initial_capability_binding_revision",
            "initial_capability_binding_digest",
            "host_client_epoch_digest",
            "created_by_actor_id",
            "created_at",
            "pin_digest",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("Session composition pin fields are closed")
        if value["schema_version"] != SESSION_COMPOSITION_PIN_SCHEMA_VERSION:
            raise ValueError("unsupported Session composition pin schema")
        pin = cls(
            pin_id=str(value["pin_id"]),
            session_id=str(value["session_id"]),
            deployment_epoch_id=str(value["deployment_epoch_id"]),
            deployment_activation_digest=str(value["deployment_activation_digest"]),
            distribution_id=str(value["distribution_id"]),
            composition_bundle_digest=str(value["composition_bundle_digest"]),
            release_identity=LayeredReleaseIdentity.from_dict(
                value["release_identity"]
            ),
            driver_bundle_digest=str(value["driver_bundle_digest"]),
            http_route_catalog_digest=str(value["http_route_catalog_digest"]),
            contribution_catalogs_digest=str(value["contribution_catalogs_digest"]),
            initial_capability_binding_id=str(
                value["initial_capability_binding_id"]
            ),
            initial_capability_binding_revision=int(
                value["initial_capability_binding_revision"]
            ),
            initial_capability_binding_digest=str(
                value["initial_capability_binding_digest"]
            ),
            created_by_actor_id=str(value["created_by_actor_id"]),
            created_at=str(value["created_at"]),
            pin_digest=str(value["pin_digest"]),
        )
        if value["host_client_epoch_digest"] != pin.host_client_epoch_digest:
            raise ValueError("Session composition host/client identity mismatch")
        if not pin.has_valid_digest():
            raise ValueError("Session composition pin digest mismatch")
        return pin


__all__ = [
    "DEPLOYMENT_ACTIVATION_EPOCH_SCHEMA_VERSION",
    "LAYERED_RELEASE_IDENTITY_SCHEMA_VERSION",
    "SESSION_COMPOSITION_PIN_SCHEMA_VERSION",
    "DeploymentActivationEpoch",
    "LayeredReleaseIdentity",
    "SessionCompositionPin",
]
