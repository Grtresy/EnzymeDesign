from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
from typing import Any

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


OFFLINE_PLUGIN_CHANGE_VERIFICATION_SCHEMA_VERSION = (
    "openzyme_offline_plugin_change_verification@1"
)


class PluginChangeKind(StrEnum):
    UPGRADE = "upgrade"
    REMOVE = "remove"


class PluginStateDisposition(StrEnum):
    NONE_REQUIRED = "none_required"
    MIGRATE = "migrate"
    RETAIN_COMPATIBLE = "retain_compatible"
    ARCHIVE = "archive"
    DELETE_VERIFIED = "delete_verified"
    TRANSFER = "transfer"
    UNDECLARED = "undeclared"


@dataclass(frozen=True, slots=True)
class PluginSessionPinObservation:
    session_id: str
    pin_digest: str
    terminal: bool
    explicitly_migrated: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.session_id, field_name="session_id")
        require_digest(self.pin_digest, field_name="pin_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "pin_digest": self.pin_digest,
            "terminal": self.terminal,
            "explicitly_migrated": self.explicitly_migrated,
        }


@dataclass(frozen=True, slots=True)
class PluginContinuationObservation:
    continuation_id: str
    session_id: str
    source_version: int
    terminal: bool

    def __post_init__(self) -> None:
        require_identifier(self.continuation_id, field_name="continuation_id")
        require_identifier(self.session_id, field_name="session_id")
        if self.source_version < 1:
            raise ValueError("source_version must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "continuation_id": self.continuation_id,
            "session_id": self.session_id,
            "source_version": self.source_version,
            "terminal": self.terminal,
        }


@dataclass(frozen=True, slots=True)
class PluginOwnedStateObservation:
    state_namespace: str
    row_count: int
    state_digest: str
    disposition: PluginStateDisposition
    disposition_receipt_digest: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.state_namespace, field_name="state_namespace")
        if self.row_count < 0:
            raise ValueError("row_count must not be negative")
        require_digest(self.state_digest, field_name="state_digest")
        if self.disposition_receipt_digest is not None:
            require_digest(
                self.disposition_receipt_digest,
                field_name="disposition_receipt_digest",
            )
        if self.row_count and self.disposition is not PluginStateDisposition.UNDECLARED:
            if self.disposition_receipt_digest is None:
                raise ValueError("non-empty state disposition requires a receipt digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_namespace": self.state_namespace,
            "row_count": self.row_count,
            "state_digest": self.state_digest,
            "disposition": self.disposition.value,
            "disposition_receipt_digest": self.disposition_receipt_digest,
        }


@dataclass(frozen=True, slots=True)
class PluginOperationObservation:
    operation_id: str
    source_version: int
    terminal: bool
    effect_settled: bool

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, field_name="operation_id")
        if self.source_version < 1:
            raise ValueError("source_version must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "source_version": self.source_version,
            "terminal": self.terminal,
            "effect_settled": self.effect_settled,
        }


@dataclass(frozen=True, slots=True)
class OfflinePluginChangeRequest:
    change_id: str
    change_kind: PluginChangeKind
    plugin_id: str
    current_manifest_digest: str
    proposed_manifest_digest: str | None
    migration_plan_digest: str | None
    quiescence_receipt_digest: str
    deployment_quiescent: bool
    session_pins: tuple[PluginSessionPinObservation, ...] = ()
    continuations: tuple[PluginContinuationObservation, ...] = ()
    owned_state: tuple[PluginOwnedStateObservation, ...] = ()
    operations: tuple[PluginOperationObservation, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.change_id, field_name="change_id")
        require_identifier(self.plugin_id, field_name="plugin_id")
        require_digest(
            self.current_manifest_digest,
            field_name="current_manifest_digest",
        )
        require_digest(
            self.quiescence_receipt_digest,
            field_name="quiescence_receipt_digest",
        )
        if self.proposed_manifest_digest is not None:
            require_digest(
                self.proposed_manifest_digest,
                field_name="proposed_manifest_digest",
            )
        if self.migration_plan_digest is not None:
            require_digest(
                self.migration_plan_digest,
                field_name="migration_plan_digest",
            )
        if self.change_kind is PluginChangeKind.UPGRADE:
            if (
                self.proposed_manifest_digest is None
                or self.proposed_manifest_digest == self.current_manifest_digest
            ):
                raise ValueError("upgrade requires a distinct proposed manifest")
        elif self.proposed_manifest_digest is not None:
            raise ValueError("removal must not carry a proposed manifest")
        for values, identity in (
            (self.session_pins, lambda item: item.session_id),
            (self.continuations, lambda item: item.continuation_id),
            (self.owned_state, lambda item: item.state_namespace),
            (self.operations, lambda item: item.operation_id),
        ):
            identities = [identity(item) for item in values]
            if len(set(identities)) != len(identities):
                raise ValueError("offline observations contain duplicate identities")


@dataclass(frozen=True, slots=True)
class PluginChangeBlocker:
    code: str
    identity: str

    def __post_init__(self) -> None:
        require_identifier(self.code, field_name="code")
        require_identifier(self.identity, field_name="identity")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "identity": self.identity}


@dataclass(frozen=True, slots=True)
class OfflinePluginChangeVerification:
    change_id: str
    plugin_id: str
    change_kind: PluginChangeKind
    allowed: bool
    blockers: tuple[PluginChangeBlocker, ...]
    mutation_applied: bool
    fallback_performed: bool
    verification_digest: str

    @classmethod
    def create(
        cls,
        request: OfflinePluginChangeRequest,
        blockers: tuple[PluginChangeBlocker, ...],
    ) -> "OfflinePluginChangeVerification":
        verification = cls(
            change_id=request.change_id,
            plugin_id=request.plugin_id,
            change_kind=request.change_kind,
            allowed=not blockers,
            blockers=blockers,
            mutation_applied=False,
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
        require_identifier(self.change_id, field_name="change_id")
        require_identifier(self.plugin_id, field_name="plugin_id")
        require_digest(self.verification_digest, field_name="verification_digest")
        object.__setattr__(
            self,
            "blockers",
            tuple(sorted(self.blockers, key=lambda item: (item.code, item.identity))),
        )
        if self.allowed == bool(self.blockers):
            raise ValueError("allowed must be the inverse of blocker presence")
        if self.mutation_applied or self.fallback_performed:
            raise ValueError("offline verification must not mutate or fallback")
        placeholder = "sha256:" + "0" * 64
        if (
            self.verification_digest != placeholder
            and self.verification_digest
            != canonical_sha256_digest(self.digest_payload())
        ):
            raise ValueError("offline verification digest mismatch")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": OFFLINE_PLUGIN_CHANGE_VERIFICATION_SCHEMA_VERSION,
            "change_id": self.change_id,
            "plugin_id": self.plugin_id,
            "change_kind": self.change_kind.value,
            "allowed": self.allowed,
            "blockers": [item.to_dict() for item in self.blockers],
            "mutation_applied": self.mutation_applied,
            "fallback_performed": self.fallback_performed,
        }


def verify_offline_plugin_change(
    request: OfflinePluginChangeRequest,
) -> OfflinePluginChangeVerification:
    blockers: list[PluginChangeBlocker] = []
    if not request.deployment_quiescent:
        blockers.append(PluginChangeBlocker("deployment_not_quiescent", request.change_id))
    for pin in request.session_pins:
        if not pin.terminal and not pin.explicitly_migrated:
            blockers.append(
                PluginChangeBlocker("non_terminal_session_pins_plugin", pin.session_id)
            )
    for continuation in request.continuations:
        if not continuation.terminal:
            blockers.append(
                PluginChangeBlocker(
                    "non_terminal_continuation_pins_plugin",
                    continuation.continuation_id,
                )
            )
    for operation in request.operations:
        if not operation.terminal or not operation.effect_settled:
            blockers.append(
                PluginChangeBlocker(
                    "plugin_operation_unsettled",
                    operation.operation_id,
                )
            )
    for state in request.owned_state:
        if state.row_count == 0:
            continue
        allowed_dispositions = (
            {
                PluginStateDisposition.MIGRATE,
                PluginStateDisposition.RETAIN_COMPATIBLE,
            }
            if request.change_kind is PluginChangeKind.UPGRADE
            else {
                PluginStateDisposition.ARCHIVE,
                PluginStateDisposition.DELETE_VERIFIED,
                PluginStateDisposition.TRANSFER,
            }
        )
        if state.disposition not in allowed_dispositions:
            blockers.append(
                PluginChangeBlocker(
                    "plugin_state_disposition_missing",
                    state.state_namespace,
                )
            )
    if (
        request.change_kind is PluginChangeKind.UPGRADE
        and request.migration_plan_digest is None
        and any(item.row_count for item in request.owned_state)
    ):
        blockers.append(
            PluginChangeBlocker("plugin_migration_plan_missing", request.plugin_id)
        )
    return OfflinePluginChangeVerification.create(request, tuple(blockers))


__all__ = [
    "OFFLINE_PLUGIN_CHANGE_VERIFICATION_SCHEMA_VERSION",
    "OfflinePluginChangeRequest",
    "OfflinePluginChangeVerification",
    "PluginChangeBlocker",
    "PluginChangeKind",
    "PluginContinuationObservation",
    "PluginOperationObservation",
    "PluginOwnedStateObservation",
    "PluginSessionPinObservation",
    "PluginStateDisposition",
    "verify_offline_plugin_change",
]
