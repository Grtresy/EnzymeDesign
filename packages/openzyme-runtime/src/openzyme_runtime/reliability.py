from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
import re
import threading
from typing import Any

from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import MutationWriterKind

from .environment_contract import EnvironmentFieldDescriptor
from .environment_contract import field_map


RELIABILITY_REFACTOR_SETTINGS_SCHEMA_VERSION = "reliability_refactor_settings@1"
RELIABILITY_SHADOW_OBSERVATION_SCHEMA_VERSION = "reliability_shadow_observation@1"
_SAFE_ROUTE_POLICY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,191}")
_RUNNER_PHASES = frozenset(
    {
        "connect",
        "layout",
        "transfer",
        "preflight",
        "dispatch",
        "poll",
        "terminal",
        "fetch",
        "shutdown",
        "unknown",
    }
)


class ShadowObservabilityMode(StrEnum):
    DISABLED = "disabled"
    SHADOW_V1 = "shadow_v1"


class ControlledOperationOwnerPolicy(StrEnum):
    LEGACY_ONLY_V1 = "legacy_only_v1"
    ROUTE_ALLOWLIST_V1 = "route_allowlist_v1"
    DURABLE_ONLY_V1 = "durable_only_v1"


class RuntimeDrainContract(StrEnum):
    SYNC_V1 = "sync_v1"
    COMMAND_V1 = "command_v1"


class MutationClosureMode(StrEnum):
    LEGACY_V1 = "legacy_v1"
    GENERIC_V1 = "generic_v1"


RELIABILITY_ENVIRONMENT_FIELDS = (
    EnvironmentFieldDescriptor(
        setting_path="reliability.shadow_observability",
        environment_names=("OPENZYME_RELIABILITY_SHADOW_OBSERVABILITY",),
        value_kind="string",
        safe_generic_default=ShadowObservabilityMode.DISABLED.value,
        strip_value=True,
        accepted_values=tuple(sorted(item.value for item in ShadowObservabilityMode)),
    ),
    EnvironmentFieldDescriptor(
        setting_path="reliability.controlled_operation_owner_policy",
        environment_names=("OPENZYME_RELIABILITY_CONTROLLED_OPERATION_OWNER_POLICY",),
        value_kind="string",
        safe_generic_default=ControlledOperationOwnerPolicy.LEGACY_ONLY_V1.value,
        strip_value=True,
        accepted_values=tuple(
            sorted(item.value for item in ControlledOperationOwnerPolicy)
        ),
    ),
    EnvironmentFieldDescriptor(
        setting_path="reliability.durable_execution_route_allowlist",
        environment_names=("OPENZYME_RELIABILITY_DURABLE_EXECUTION_ROUTE_ALLOWLIST",),
        value_kind="string_list",
        safe_generic_default=[],
        list_normalization="sorted_unique",
    ),
    EnvironmentFieldDescriptor(
        setting_path="reliability.runtime_drain_contract",
        environment_names=("OPENZYME_RELIABILITY_RUNTIME_DRAIN_CONTRACT",),
        value_kind="string",
        safe_generic_default=RuntimeDrainContract.COMMAND_V1.value,
        strip_value=True,
        accepted_values=tuple(sorted(item.value for item in RuntimeDrainContract)),
    ),
    EnvironmentFieldDescriptor(
        setting_path="reliability.mutation_closure_mode",
        environment_names=("OPENZYME_RELIABILITY_MUTATION_CLOSURE_MODE",),
        value_kind="string",
        safe_generic_default=MutationClosureMode.LEGACY_V1.value,
        strip_value=True,
        accepted_values=tuple(sorted(item.value for item in MutationClosureMode)),
    ),
    EnvironmentFieldDescriptor(
        setting_path="reliability.shadow_max_observations",
        environment_names=("OPENZYME_RELIABILITY_SHADOW_MAX_OBSERVATIONS",),
        value_kind="integer",
        safe_generic_default=256,
    ),
)
_RELIABILITY_ENVIRONMENT_FIELD_MAP = field_map(RELIABILITY_ENVIRONMENT_FIELDS)


def reliability_environment_fields() -> tuple[EnvironmentFieldDescriptor, ...]:
    return RELIABILITY_ENVIRONMENT_FIELDS


def _resolved_environment_field(
    setting_path: str,
    environ: Mapping[str, str],
) -> object:
    return _RELIABILITY_ENVIRONMENT_FIELD_MAP[setting_path].resolve(environ)


@dataclass(frozen=True, slots=True)
class ReliabilityRefactorSettings:
    shadow_observability: ShadowObservabilityMode = ShadowObservabilityMode.DISABLED
    controlled_operation_owner_policy: ControlledOperationOwnerPolicy = (
        ControlledOperationOwnerPolicy.LEGACY_ONLY_V1
    )
    durable_execution_route_allowlist: tuple[str, ...] = ()
    runtime_drain_contract: RuntimeDrainContract = RuntimeDrainContract.COMMAND_V1
    mutation_closure_mode: MutationClosureMode = MutationClosureMode.LEGACY_V1
    shadow_max_observations: int = 256

    def __post_init__(self) -> None:
        if self.shadow_max_observations <= 0 or self.shadow_max_observations > 4_096:
            raise ValueError(
                "OPENZYME_RELIABILITY_SHADOW_MAX_OBSERVATIONS must be between 1 "
                "and 4096"
            )
        normalized = tuple(sorted(set(self.durable_execution_route_allowlist)))
        if normalized != self.durable_execution_route_allowlist:
            raise ValueError(
                "durable execution route allowlist must be sorted and unique"
            )
        for route_policy_id in normalized:
            if _SAFE_ROUTE_POLICY_PATTERN.fullmatch(route_policy_id) is None:
                raise ValueError(
                    "durable execution route allowlist contains an invalid route "
                    "policy id"
                )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ReliabilityRefactorSettings":
        source = os.environ if environ is None else environ
        allowlist = tuple(
            _resolved_environment_field(
                "reliability.durable_execution_route_allowlist",
                source,
            )
        )
        return cls(
            shadow_observability=ShadowObservabilityMode(
                _resolved_environment_field(
                    "reliability.shadow_observability",
                    source,
                )
            ),
            controlled_operation_owner_policy=ControlledOperationOwnerPolicy(
                _resolved_environment_field(
                    "reliability.controlled_operation_owner_policy",
                    source,
                )
            ),
            durable_execution_route_allowlist=allowlist,
            runtime_drain_contract=RuntimeDrainContract(
                _resolved_environment_field(
                    "reliability.runtime_drain_contract",
                    source,
                )
            ),
            mutation_closure_mode=MutationClosureMode(
                _resolved_environment_field(
                    "reliability.mutation_closure_mode",
                    source,
                )
            ),
            shadow_max_observations=int(
                _resolved_environment_field(
                    "reliability.shadow_max_observations",
                    source,
                )
            ),
        )

    def owner_mode_for_route(
        self, route_policy_id: str
    ) -> ControlledOperationOwnerMode:
        if _SAFE_ROUTE_POLICY_PATTERN.fullmatch(route_policy_id) is None:
            raise ValueError("route_policy_id is invalid")
        if (
            self.controlled_operation_owner_policy
            is ControlledOperationOwnerPolicy.DURABLE_ONLY_V1
        ):
            return ControlledOperationOwnerMode.DURABLE_ASYNC_V1
        if (
            self.controlled_operation_owner_policy
            is ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1
            and route_policy_id in self.durable_execution_route_allowlist
        ):
            return ControlledOperationOwnerMode.DURABLE_ASYNC_V1
        return ControlledOperationOwnerMode.LEGACY_SYNC

    @property
    def config_digest(self) -> str:
        payload = {
            "schema_version": RELIABILITY_REFACTOR_SETTINGS_SCHEMA_VERSION,
            "shadow_observability": self.shadow_observability.value,
            "controlled_operation_owner_policy": (
                self.controlled_operation_owner_policy.value
            ),
            "durable_execution_route_allowlist": list(
                self.durable_execution_route_allowlist
            ),
            "runtime_drain_contract": self.runtime_drain_contract.value,
            "mutation_closure_mode": self.mutation_closure_mode.value,
            "shadow_max_observations": self.shadow_max_observations,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


class ReliabilityShadowObservationKind(StrEnum):
    APPROVAL_WAIT = "approval_wait"
    RUNTIME_AUTHORITY_HOLD = "runtime_authority_hold"
    RUNNER_PHASE_EFFECT = "runner_phase_effect"
    MUTATION_WRITER_CATEGORY = "mutation_writer_category"
    PUBLIC_REDACTION = "public_redaction"


@dataclass(frozen=True, slots=True)
class ReliabilityShadowObservation:
    sequence: int
    kind: ReliabilityShadowObservationKind
    subject_digest: str
    dimensions: dict[str, bool | int | str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RELIABILITY_SHADOW_OBSERVATION_SCHEMA_VERSION,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "subject_digest": self.subject_digest,
            "dimensions": dict(self.dimensions),
        }


class ReliabilityShadowObserver:
    """Host-private bounded telemetry that cannot authorize execution or retry."""

    def __init__(self, settings: ReliabilityRefactorSettings) -> None:
        self._mode = settings.shadow_observability
        self._observations: deque[ReliabilityShadowObservation] = deque(
            maxlen=settings.shadow_max_observations
        )
        self._lock = threading.Lock()
        self._sequence = 0

    @property
    def enabled(self) -> bool:
        return self._mode is ShadowObservabilityMode.SHADOW_V1

    def observe_approval_wait(
        self,
        *,
        operation_id: str,
        elapsed_ms: int,
        resolution: str,
    ) -> None:
        if resolution not in {
            "approved",
            "rejected",
            "expired",
            "cancelled",
            "recovery_failed",
        }:
            raise ValueError("approval shadow resolution is not closed")
        self._append(
            kind=ReliabilityShadowObservationKind.APPROVAL_WAIT,
            subject=operation_id,
            dimensions={
                "elapsed_ms": _bounded_milliseconds(elapsed_ms),
                "resolution": resolution,
            },
        )

    def observe_runtime_authority_hold(
        self,
        *,
        signal_id: str,
        signal_hold_ms: int,
        session_lease_hold_ms: int,
    ) -> None:
        self._append(
            kind=ReliabilityShadowObservationKind.RUNTIME_AUTHORITY_HOLD,
            subject=signal_id,
            dimensions={
                "signal_hold_ms": _bounded_milliseconds(signal_hold_ms),
                "session_lease_hold_ms": _bounded_milliseconds(session_lease_hold_ms),
            },
        )

    def observe_runner_phase_effect(
        self,
        *,
        operation_id: str,
        phase: str,
        effect_certainty: ExternalEffectCertainty,
    ) -> None:
        if phase not in _RUNNER_PHASES:
            raise ValueError("runner shadow phase is not closed")
        if not isinstance(effect_certainty, ExternalEffectCertainty):
            raise ValueError("runner effect certainty must use the closed domain enum")
        self._append(
            kind=ReliabilityShadowObservationKind.RUNNER_PHASE_EFFECT,
            subject=operation_id,
            dimensions={
                "phase": phase,
                "effect_certainty": effect_certainty.value,
            },
        )

    def observe_mutation_writer_category(
        self,
        *,
        scope_id: str,
        writer_kind: MutationWriterKind,
        admitted: bool,
    ) -> None:
        if not isinstance(writer_kind, MutationWriterKind):
            raise ValueError("mutation writer kind must use the closed domain enum")
        self._append(
            kind=ReliabilityShadowObservationKind.MUTATION_WRITER_CATEGORY,
            subject=scope_id,
            dimensions={"writer_kind": writer_kind.value, "admitted": admitted},
        )

    def observe_public_redaction(
        self,
        *,
        projection_name: str,
        removed_field_count: int,
        residual_private_marker_detected: bool,
    ) -> None:
        if _SAFE_ROUTE_POLICY_PATTERN.fullmatch(projection_name) is None:
            raise ValueError("projection_name is invalid")
        if removed_field_count < 0 or removed_field_count > 1_000_000:
            raise ValueError("removed_field_count is outside the bounded range")
        self._append(
            kind=ReliabilityShadowObservationKind.PUBLIC_REDACTION,
            subject=projection_name,
            dimensions={
                "removed_field_count": removed_field_count,
                "residual_private_marker_detected": (residual_private_marker_detected),
            },
        )

    def snapshot(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(item.to_dict() for item in self._observations)

    def _append(
        self,
        *,
        kind: ReliabilityShadowObservationKind,
        subject: str,
        dimensions: dict[str, bool | int | str],
    ) -> None:
        if not self.enabled:
            return
        subject_digest = "sha256:" + hashlib.sha256(subject.encode("utf-8")).hexdigest()
        with self._lock:
            self._sequence += 1
            self._observations.append(
                ReliabilityShadowObservation(
                    sequence=self._sequence,
                    kind=kind,
                    subject_digest=subject_digest,
                    dimensions=dict(dimensions),
                )
            )


def _bounded_milliseconds(value: int) -> int:
    if value < 0:
        raise ValueError("elapsed milliseconds cannot be negative")
    return min(value, 86_400_000)
