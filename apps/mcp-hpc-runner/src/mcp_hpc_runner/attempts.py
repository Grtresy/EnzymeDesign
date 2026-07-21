from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Any
from typing import ClassVar

from .config import RunnerConfig
from .models import RunSpec
from .store import ArtifactStore
from .transport import SshTransportManager


RUNNER_ATTEMPT_SCHEMA_VERSION = "runner_attempt@1"
RUNNER_ATTEMPT_EVENT_SCHEMA_VERSION = "runner_attempt_event@1"
RUNNER_ATTEMPT_SAFE_RECEIPT_SCHEMA_VERSION = "runner_attempt_safe_receipt@1"
RUNNER_ATTEMPT_QUARANTINE_SCHEMA_VERSION = "runner_attempt_quarantine@1"
_SNAPSHOT_NAME = "runner_attempt.json"
_QUARANTINE_NAME = "runner_attempt_quarantine.json"
_EVENT_PREFIX = "runner_attempt_event_"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_ATTEMPT_EVENT_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "attempt_id",
        "run_id",
        "run_binding_digest",
        "operation_binding_digest",
        "execution_binding_digest",
        "approval_binding_digest",
        "runspec_digest",
        "route_digest",
        "expected_outputs_digest",
        "input_contract_digest",
        "effective_config_digest",
        "transport_identity_digest",
        "transport_policy_digest",
        "selected_mode",
        "route_policy",
        "phase",
        "state",
        "effect_certainty",
        "retry_eligibility",
        "reconciliation_required",
        "state_version",
        "phase_attempt_counts",
        "pre_effect_recovery_attempts_used",
        "transport_generation",
        "receipt_digests",
        "safe_failure_code",
        "created_at",
        "updated_at",
    }
)
_ATTEMPT_PERSISTED_FIELDS = _ATTEMPT_EVENT_SNAPSHOT_FIELDS | {
    "journal_head_digest",
    "safe_receipt_digest",
}
_ATTEMPT_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "reason_code",
        "occurred_at",
        "previous_event_digest",
        "attempt_snapshot",
        "event_digest",
    }
)


class RunnerAttemptPhase(StrEnum):
    ALLOCATED = "allocated"
    TRANSPORT_READY = "transport_ready"
    REMOTE_LAYOUT_READY = "remote_layout_ready"
    INPUT_STAGING = "input_staging"
    INPUTS_VERIFIED = "inputs_verified"
    PREFLIGHT_PASSED = "preflight_passed"
    DISPATCH_PREPARED = "dispatch_prepared"
    DISPATCHING = "dispatching"
    REMOTE_PENDING = "remote_pending"
    REMOTE_TERMINAL = "remote_terminal"
    OUTPUTS_FETCHING = "outputs_fetching"
    OUTPUTS_VERIFIED = "outputs_verified"
    TERMINAL = "terminal"


class RunnerAttemptState(StrEnum):
    ACTIVE = "active"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    TERMINAL = "terminal"
    QUARANTINED = "quarantined"


class RunnerEffectCertainty(StrEnum):
    NO_EFFECT = "no_effect"
    DISPATCH_IN_DOUBT = "dispatch_in_doubt"
    EFFECT_KNOWN = "effect_known"
    TERMINAL_KNOWN = "terminal_known"


class RunnerRetryEligibility(StrEnum):
    SAME_PHASE_SAFE = "same_phase_safe"
    VERIFY_THEN_RETRY = "verify_then_retry"
    RECONCILE_REQUIRED = "reconcile_required"
    TERMINAL = "terminal"


_PHASE_ORDER = {phase: index for index, phase in enumerate(RunnerAttemptPhase)}
_EFFECT_ORDER = {
    RunnerEffectCertainty.NO_EFFECT: 0,
    RunnerEffectCertainty.DISPATCH_IN_DOUBT: 1,
    RunnerEffectCertainty.EFFECT_KNOWN: 2,
    RunnerEffectCertainty.TERMINAL_KNOWN: 3,
}
_STATE_TRANSITIONS = {
    RunnerAttemptState.ACTIVE: frozenset(
        {
            RunnerAttemptState.ACTIVE,
            RunnerAttemptState.RECONCILIATION_REQUIRED,
            RunnerAttemptState.TERMINAL,
            RunnerAttemptState.QUARANTINED,
        }
    ),
    RunnerAttemptState.RECONCILIATION_REQUIRED: frozenset(
        {
            RunnerAttemptState.ACTIVE,
            RunnerAttemptState.RECONCILIATION_REQUIRED,
            RunnerAttemptState.TERMINAL,
            RunnerAttemptState.QUARANTINED,
        }
    ),
    RunnerAttemptState.TERMINAL: frozenset(),
    RunnerAttemptState.QUARANTINED: frozenset(),
}


def runner_phase_precedes(
    current: RunnerAttemptPhase,
    target: RunnerAttemptPhase,
) -> bool:
    return _PHASE_ORDER[current] < _PHASE_ORDER[target]


_RETRY_TRANSITIONS = {
    RunnerRetryEligibility.SAME_PHASE_SAFE: frozenset(RunnerRetryEligibility),
    RunnerRetryEligibility.VERIFY_THEN_RETRY: frozenset(
        {
            RunnerRetryEligibility.VERIFY_THEN_RETRY,
            RunnerRetryEligibility.RECONCILE_REQUIRED,
            RunnerRetryEligibility.TERMINAL,
        }
    ),
    RunnerRetryEligibility.RECONCILE_REQUIRED: frozenset(
        {
            RunnerRetryEligibility.VERIFY_THEN_RETRY,
            RunnerRetryEligibility.RECONCILE_REQUIRED,
            RunnerRetryEligibility.TERMINAL,
        }
    ),
    RunnerRetryEligibility.TERMINAL: frozenset(
        {RunnerRetryEligibility.TERMINAL}
    ),
}


class RunnerAttemptError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


class RunnerAttemptExistsError(RunnerAttemptError):
    pass


class RunnerAttemptQuarantined(RunnerAttemptError):
    pass


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _require_digest(value: object, *, field_name: str) -> str:
    normalized = str(value)
    if _SHA256.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a sha256 digest")
    return normalized


def _binding_digest(kind: str, value: object) -> str:
    return canonical_digest(
        {
            "schema_version": "runner_attempt_binding@1",
            "kind": kind,
            "value": value,
        }
    )


def _binding_material(spec: RunSpec, selected_mode: str) -> dict[str, str]:
    metadata = dict(spec.metadata or {})
    openzyme = dict(metadata.get("openzyme") or {})
    operation = {
        key: openzyme.get(key)
        for key in (
            "controlled_operation_id",
            "controlled_operation_digest",
            "operation_id",
            "operation_digest",
        )
    }
    execution = {
        "controlled_operation_execution_id": openzyme.get(
            "controlled_operation_execution_id"
        ),
        "controlled_operation_execution_digest": openzyme.get(
            "controlled_operation_execution_digest"
        ),
        "engine_invocation_id": openzyme.get("engine_invocation_id")
        or metadata.get("pipeline_invocation_id"),
        "pipeline_step_id": metadata.get("pipeline_step_id"),
    }
    approval = {
        key: openzyme.get(key)
        for key in ("approval_id", "approval_digest", "approval_decision_digest")
    }
    route_policy = "ssh_direct@1" if selected_mode == "ssh" else "slurm_job@1"
    route = {
        "selected_mode": selected_mode,
        "route_policy": route_policy,
        "requested_mode": spec.execution_mode,
        "runner_contract_digest": dict(metadata.get("tool_contract") or {}).get(
            "runner_contract_digest"
        ),
        "toolchain_runtime_request": metadata.get("toolchain_runtime_request"),
    }
    return {
        "run_binding_digest": _binding_digest("run", {"run_id": spec.run_id}),
        "operation_binding_digest": _binding_digest("operation", operation),
        "execution_binding_digest": _binding_digest("execution", execution),
        "approval_binding_digest": _binding_digest("approval", approval),
        "route_digest": _binding_digest("route", route),
        "expected_outputs_digest": _binding_digest(
            "expected_outputs",
            [item.to_dict() for item in spec.expected_outputs],
        ),
        "input_contract_digest": _binding_digest(
            "inputs",
            [item.to_dict() for item in spec.inputs],
        ),
        "route_policy": route_policy,
    }


@dataclass(frozen=True, slots=True)
class RunnerAttempt:
    SCHEMA_VERSION: ClassVar[str] = RUNNER_ATTEMPT_SCHEMA_VERSION

    attempt_id: str
    run_id: str
    run_binding_digest: str
    operation_binding_digest: str
    execution_binding_digest: str
    approval_binding_digest: str
    runspec_digest: str
    route_digest: str
    expected_outputs_digest: str
    input_contract_digest: str
    effective_config_digest: str
    transport_identity_digest: str
    transport_policy_digest: str
    selected_mode: str
    route_policy: str
    phase: RunnerAttemptPhase
    state: RunnerAttemptState
    effect_certainty: RunnerEffectCertainty
    retry_eligibility: RunnerRetryEligibility
    reconciliation_required: bool
    state_version: int
    phase_attempt_counts: dict[str, int]
    pre_effect_recovery_attempts_used: int
    transport_generation: int
    receipt_digests: dict[str, str]
    safe_failure_code: str | None
    created_at: str
    updated_at: str
    journal_head_digest: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "attempt_id",
            "run_binding_digest",
            "operation_binding_digest",
            "execution_binding_digest",
            "approval_binding_digest",
            "runspec_digest",
            "route_digest",
            "expected_outputs_digest",
            "input_contract_digest",
            "effective_config_digest",
            "transport_identity_digest",
            "transport_policy_digest",
        ):
            _require_digest(getattr(self, field_name), field_name=field_name)
        if self.journal_head_digest is not None:
            _require_digest(
                self.journal_head_digest,
                field_name="journal_head_digest",
            )
        if self.selected_mode not in {"ssh", "sbatch"}:
            raise ValueError("selected_mode must be ssh or sbatch")
        expected_policy = (
            "ssh_direct@1" if self.selected_mode == "ssh" else "slurm_job@1"
        )
        if self.route_policy != expected_policy:
            raise ValueError("route_policy does not match selected_mode")
        if self.state_version < 1:
            raise ValueError("state_version must be positive")
        if self.transport_generation < 0:
            raise ValueError("transport_generation must be non-negative")
        if (
            self.pre_effect_recovery_attempts_used < 0
            or self.pre_effect_recovery_attempts_used > 1
        ):
            raise ValueError("pre-effect recovery count is outside the closed bound")
        if not self.run_id:
            raise ValueError("run_id must not be empty")
        for phase, count in self.phase_attempt_counts.items():
            RunnerAttemptPhase(phase)
            if isinstance(count, bool) or count < 1 or count > 1_000_000:
                raise ValueError("phase attempt count is outside the closed bound")
        if self.phase.value not in self.phase_attempt_counts:
            raise ValueError("current phase is missing from phase_attempt_counts")
        for name, digest in self.receipt_digests.items():
            if _SAFE_CODE.fullmatch(name) is None:
                raise ValueError("receipt digest name is invalid")
            _require_digest(digest, field_name=f"receipt_digests.{name}")
        if self.safe_failure_code is not None and _SAFE_CODE.fullmatch(
            self.safe_failure_code
        ) is None:
            raise ValueError("safe_failure_code is invalid")
        if self.state is RunnerAttemptState.RECONCILIATION_REQUIRED:
            if (
                not self.reconciliation_required
                or self.retry_eligibility
                is not RunnerRetryEligibility.RECONCILE_REQUIRED
                or self.effect_certainty
                is not RunnerEffectCertainty.DISPATCH_IN_DOUBT
            ):
                raise ValueError("reconciliation-required state is inconsistent")
        if self.effect_certainty is RunnerEffectCertainty.DISPATCH_IN_DOUBT:
            if not self.reconciliation_required:
                raise ValueError("dispatch-in-doubt must require reconciliation")
        if self.state is RunnerAttemptState.TERMINAL:
            if self.phase is not RunnerAttemptPhase.TERMINAL:
                raise ValueError("terminal attempt must use terminal phase")
            if self.retry_eligibility is not RunnerRetryEligibility.TERMINAL:
                raise ValueError("terminal attempt cannot authorize retry")
        if self.state is RunnerAttemptState.ACTIVE and self.phase is RunnerAttemptPhase.TERMINAL:
            raise ValueError("active attempt cannot use terminal phase")

    @property
    def immutable_identity(self) -> tuple[object, ...]:
        return (
            self.attempt_id,
            self.run_id,
            self.run_binding_digest,
            self.operation_binding_digest,
            self.execution_binding_digest,
            self.approval_binding_digest,
            self.runspec_digest,
            self.route_digest,
            self.expected_outputs_digest,
            self.input_contract_digest,
            self.effective_config_digest,
            self.transport_identity_digest,
            self.transport_policy_digest,
            self.selected_mode,
            self.route_policy,
            self.created_at,
        )

    def _event_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "run_binding_digest": self.run_binding_digest,
            "operation_binding_digest": self.operation_binding_digest,
            "execution_binding_digest": self.execution_binding_digest,
            "approval_binding_digest": self.approval_binding_digest,
            "runspec_digest": self.runspec_digest,
            "route_digest": self.route_digest,
            "expected_outputs_digest": self.expected_outputs_digest,
            "input_contract_digest": self.input_contract_digest,
            "effective_config_digest": self.effective_config_digest,
            "transport_identity_digest": self.transport_identity_digest,
            "transport_policy_digest": self.transport_policy_digest,
            "selected_mode": self.selected_mode,
            "route_policy": self.route_policy,
            "phase": self.phase.value,
            "state": self.state.value,
            "effect_certainty": self.effect_certainty.value,
            "retry_eligibility": self.retry_eligibility.value,
            "reconciliation_required": self.reconciliation_required,
            "state_version": self.state_version,
            "phase_attempt_counts": dict(sorted(self.phase_attempt_counts.items())),
            "pre_effect_recovery_attempts_used": (
                self.pre_effect_recovery_attempts_used
            ),
            "transport_generation": self.transport_generation,
            "receipt_digests": dict(sorted(self.receipt_digests.items())),
            "safe_failure_code": self.safe_failure_code,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @property
    def safe_receipt_digest(self) -> str:
        return canonical_digest(
            {
                "schema_version": RUNNER_ATTEMPT_SAFE_RECEIPT_SCHEMA_VERSION,
                "attempt_id": self.attempt_id,
                "run_binding_digest": self.run_binding_digest,
                "state_version": self.state_version,
                "phase": self.phase.value,
                "state": self.state.value,
                "effect_certainty": self.effect_certainty.value,
                "retry_eligibility": self.retry_eligibility.value,
                "reconciliation_required": self.reconciliation_required,
                "safe_failure_code": self.safe_failure_code,
                "pre_effect_recovery_attempts_used": (
                    self.pre_effect_recovery_attempts_used
                ),
                "receipt_digests": dict(sorted(self.receipt_digests.items())),
                "journal_head_digest": self.journal_head_digest,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **self._event_snapshot(),
            "journal_head_digest": self.journal_head_digest,
            "safe_receipt_digest": self.safe_receipt_digest,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        event_snapshot: bool = False,
    ) -> RunnerAttempt:
        expected_fields = (
            _ATTEMPT_EVENT_SNAPSHOT_FIELDS
            if event_snapshot
            else _ATTEMPT_PERSISTED_FIELDS
        )
        if set(data) != expected_fields:
            raise ValueError("runner attempt contains unknown or missing fields")
        if data.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("runner attempt schema version is unsupported")
        attempt = cls(
            attempt_id=str(data["attempt_id"]),
            run_id=str(data["run_id"]),
            run_binding_digest=str(data["run_binding_digest"]),
            operation_binding_digest=str(data["operation_binding_digest"]),
            execution_binding_digest=str(data["execution_binding_digest"]),
            approval_binding_digest=str(data["approval_binding_digest"]),
            runspec_digest=str(data["runspec_digest"]),
            route_digest=str(data["route_digest"]),
            expected_outputs_digest=str(data["expected_outputs_digest"]),
            input_contract_digest=str(data["input_contract_digest"]),
            effective_config_digest=str(data["effective_config_digest"]),
            transport_identity_digest=str(data["transport_identity_digest"]),
            transport_policy_digest=str(data["transport_policy_digest"]),
            selected_mode=str(data["selected_mode"]),
            route_policy=str(data["route_policy"]),
            phase=RunnerAttemptPhase(str(data["phase"])),
            state=RunnerAttemptState(str(data["state"])),
            effect_certainty=RunnerEffectCertainty(str(data["effect_certainty"])),
            retry_eligibility=RunnerRetryEligibility(str(data["retry_eligibility"])),
            reconciliation_required=bool(data["reconciliation_required"]),
            state_version=int(data["state_version"]),
            phase_attempt_counts={
                str(key): int(value)
                for key, value in dict(data["phase_attempt_counts"]).items()
            },
            pre_effect_recovery_attempts_used=int(
                data["pre_effect_recovery_attempts_used"]
            ),
            transport_generation=int(data["transport_generation"]),
            receipt_digests={
                str(key): str(value)
                for key, value in dict(data["receipt_digests"]).items()
            },
            safe_failure_code=(
                None
                if data.get("safe_failure_code") is None
                else str(data["safe_failure_code"])
            ),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            journal_head_digest=(
                None
                if event_snapshot
                else str(data["journal_head_digest"])
            ),
        )
        if not event_snapshot:
            provided_receipt = str(data.get("safe_receipt_digest") or "")
            if provided_receipt != attempt.safe_receipt_digest:
                raise ValueError("runner attempt safe receipt digest does not verify")
        return attempt


@dataclass(frozen=True, slots=True)
class RunnerAttemptEvent:
    event_type: str
    reason_code: str
    occurred_at: str
    previous_event_digest: str | None
    attempt_snapshot: dict[str, object]
    event_digest: str

    @classmethod
    def build(
        cls,
        *,
        event_type: str,
        reason_code: str,
        previous_event_digest: str | None,
        attempt: RunnerAttempt,
    ) -> RunnerAttemptEvent:
        if _SAFE_CODE.fullmatch(event_type) is None:
            raise ValueError("runner attempt event_type is invalid")
        if _SAFE_CODE.fullmatch(reason_code) is None:
            raise ValueError("runner attempt reason_code is invalid")
        if previous_event_digest is not None:
            _require_digest(previous_event_digest, field_name="previous_event_digest")
        payload: dict[str, object] = {
            "schema_version": RUNNER_ATTEMPT_EVENT_SCHEMA_VERSION,
            "event_type": event_type,
            "reason_code": reason_code,
            "occurred_at": _now_iso(),
            "previous_event_digest": previous_event_digest,
            "attempt_snapshot": attempt._event_snapshot(),
        }
        return cls(
            event_type=event_type,
            reason_code=reason_code,
            occurred_at=str(payload["occurred_at"]),
            previous_event_digest=previous_event_digest,
            attempt_snapshot=dict(payload["attempt_snapshot"]),
            event_digest=canonical_digest(payload),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": RUNNER_ATTEMPT_EVENT_SCHEMA_VERSION,
            "event_type": self.event_type,
            "reason_code": self.reason_code,
            "occurred_at": self.occurred_at,
            "previous_event_digest": self.previous_event_digest,
            "attempt_snapshot": dict(self.attempt_snapshot),
            "event_digest": self.event_digest,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunnerAttemptEvent:
        if set(data) != _ATTEMPT_EVENT_FIELDS:
            raise ValueError("runner attempt event contains unknown or missing fields")
        if data.get("schema_version") != RUNNER_ATTEMPT_EVENT_SCHEMA_VERSION:
            raise ValueError("runner attempt event schema version is unsupported")
        payload = {
            "schema_version": RUNNER_ATTEMPT_EVENT_SCHEMA_VERSION,
            "event_type": str(data["event_type"]),
            "reason_code": str(data["reason_code"]),
            "occurred_at": str(data["occurred_at"]),
            "previous_event_digest": data.get("previous_event_digest"),
            "attempt_snapshot": dict(data["attempt_snapshot"]),
        }
        event = cls(
            event_type=str(payload["event_type"]),
            reason_code=str(payload["reason_code"]),
            occurred_at=str(payload["occurred_at"]),
            previous_event_digest=(
                None
                if payload["previous_event_digest"] is None
                else str(payload["previous_event_digest"])
            ),
            attempt_snapshot=dict(payload["attempt_snapshot"]),
            event_digest=str(data["event_digest"]),
        )
        if _SAFE_CODE.fullmatch(event.event_type) is None or _SAFE_CODE.fullmatch(
            event.reason_code
        ) is None:
            raise ValueError("runner attempt event contains an invalid code")
        _require_digest(event.event_digest, field_name="event_digest")
        if event.previous_event_digest is not None:
            _require_digest(
                event.previous_event_digest,
                field_name="previous_event_digest",
            )
        if canonical_digest(payload) != event.event_digest:
            raise ValueError("runner attempt event digest does not verify")
        return event


class RunnerAttemptJournal:
    def __init__(
        self,
        store: ArtifactStore,
        config: RunnerConfig,
        transport_manager: SshTransportManager,
    ) -> None:
        self.store = store
        self.config = config
        self.transport_manager = transport_manager
        self._lock = threading.RLock()

    def has_attempt(self, run_id: str) -> bool:
        metadata = self.store.run_root(run_id) / "metadata"
        if not metadata.is_dir() or metadata.is_symlink():
            return False
        snapshot = metadata / _SNAPSHOT_NAME
        if snapshot.exists() or snapshot.is_symlink():
            return True
        return any(
            path.name.startswith(_EVENT_PREFIX)
            for path in metadata.iterdir()
        )

    def create(self, spec: RunSpec, *, selected_mode: str) -> RunnerAttempt:
        if spec.run_id is None:
            raise ValueError("runner attempt requires a server-generated run_id")
        with self._lock:
            existing = self.store.list_metadata(spec.run_id, prefix=_EVENT_PREFIX)
            snapshot_path = self.store.run_root(spec.run_id) / "metadata" / _SNAPSHOT_NAME
            if existing or snapshot_path.exists() or snapshot_path.is_symlink():
                raise RunnerAttemptExistsError(
                    "runner_attempt_exists",
                    "runner attempt already exists; payload replay is refused",
                )
            bindings = _binding_material(spec, selected_mode)
            runspec_digest = canonical_digest(spec.to_dict())
            created_at = _now_iso()
            identity = {
                "schema_version": RUNNER_ATTEMPT_SCHEMA_VERSION,
                "run_binding_digest": bindings["run_binding_digest"],
                "runspec_digest": runspec_digest,
                "operation_binding_digest": bindings["operation_binding_digest"],
                "execution_binding_digest": bindings["execution_binding_digest"],
                "approval_binding_digest": bindings["approval_binding_digest"],
                "route_digest": bindings["route_digest"],
                "expected_outputs_digest": bindings["expected_outputs_digest"],
                "input_contract_digest": bindings["input_contract_digest"],
                "effective_config_digest": self.config.effective_config_digest,
                "transport_identity_digest": (
                    self.transport_manager.identity.identity_digest
                ),
                "transport_policy_digest": self.config.ssh_transport.policy_digest,
            }
            attempt = RunnerAttempt(
                attempt_id=canonical_digest(identity),
                run_id=spec.run_id,
                run_binding_digest=bindings["run_binding_digest"],
                operation_binding_digest=bindings["operation_binding_digest"],
                execution_binding_digest=bindings["execution_binding_digest"],
                approval_binding_digest=bindings["approval_binding_digest"],
                runspec_digest=runspec_digest,
                route_digest=bindings["route_digest"],
                expected_outputs_digest=bindings["expected_outputs_digest"],
                input_contract_digest=bindings["input_contract_digest"],
                effective_config_digest=self.config.effective_config_digest,
                transport_identity_digest=(
                    self.transport_manager.identity.identity_digest
                ),
                transport_policy_digest=self.config.ssh_transport.policy_digest,
                selected_mode=selected_mode,
                route_policy=bindings["route_policy"],
                phase=RunnerAttemptPhase.ALLOCATED,
                state=RunnerAttemptState.ACTIVE,
                effect_certainty=RunnerEffectCertainty.NO_EFFECT,
                retry_eligibility=RunnerRetryEligibility.SAME_PHASE_SAFE,
                reconciliation_required=False,
                state_version=1,
                phase_attempt_counts={RunnerAttemptPhase.ALLOCATED.value: 1},
                pre_effect_recovery_attempts_used=0,
                transport_generation=0,
                receipt_digests={},
                safe_failure_code=None,
                created_at=created_at,
                updated_at=created_at,
            )
            return self._append(attempt, event_type="created", reason_code="allocated")

    def load(self, run_id: str) -> RunnerAttempt:
        with self._lock:
            try:
                self.store.read_json(run_id, _QUARANTINE_NAME)
            except FileNotFoundError:
                pass
            else:
                raise RunnerAttemptQuarantined(
                    "runner_attempt_quarantined",
                    "runner attempt is quarantined and cannot perform remote work",
                )
            try:
                return self._load_verified(run_id)
            except RunnerAttemptQuarantined:
                raise
            except Exception as exc:  # noqa: BLE001 - convert private parse errors.
                self._quarantine(run_id, reason_code="journal_validation_failed")
                raise RunnerAttemptQuarantined(
                    "runner_attempt_journal_invalid",
                    "runner attempt journal validation failed",
                ) from exc

    def load_bound(
        self,
        run_id: str,
        spec: RunSpec,
        *,
        selected_mode: str,
    ) -> RunnerAttempt:
        with self._lock:
            attempt = self.load(run_id)
            bindings = _binding_material(spec, selected_mode)
            expected = (
                bindings["run_binding_digest"],
                bindings["operation_binding_digest"],
                bindings["execution_binding_digest"],
                bindings["approval_binding_digest"],
                canonical_digest(spec.to_dict()),
                bindings["route_digest"],
                bindings["expected_outputs_digest"],
                bindings["input_contract_digest"],
                self.config.effective_config_digest,
                self.transport_manager.identity.identity_digest,
                self.config.ssh_transport.policy_digest,
                selected_mode,
                bindings["route_policy"],
            )
            actual = attempt.immutable_identity[2:15]
            if actual != expected:
                self._quarantine(run_id, reason_code="attempt_identity_drift")
                raise RunnerAttemptQuarantined(
                    "runner_attempt_identity_drift",
                    "runner attempt identity drifted from the frozen request",
                )
            return attempt

    def transition(
        self,
        run_id: str,
        *,
        phase: RunnerAttemptPhase | None = None,
        state: RunnerAttemptState | None = None,
        effect_certainty: RunnerEffectCertainty | None = None,
        retry_eligibility: RunnerRetryEligibility | None = None,
        reconciliation_required: bool | None = None,
        transport_generation: int | None = None,
        receipt_digests: dict[str, str] | None = None,
        safe_failure_code: str | None = None,
        increment_phase_attempt: bool = False,
        consume_pre_effect_recovery: bool = False,
        event_type: str = "transitioned",
        reason_code: str,
        expected_state_version: int | None = None,
    ) -> RunnerAttempt:
        with self._lock:
            current = self.load(run_id)
            if (
                expected_state_version is not None
                and current.state_version != expected_state_version
            ):
                raise RunnerAttemptError(
                    "runner_attempt_state_conflict",
                    "runner attempt state version changed",
                )
            next_phase = phase or current.phase
            next_state = state or current.state
            next_effect = effect_certainty or current.effect_certainty
            next_retry = retry_eligibility or current.retry_eligibility
            next_reconciliation = (
                current.reconciliation_required
                if reconciliation_required is None
                else reconciliation_required
            )
            next_generation = (
                current.transport_generation
                if transport_generation is None
                else transport_generation
            )
            counts = dict(current.phase_attempt_counts)
            if next_phase is not current.phase or increment_phase_attempt:
                counts[next_phase.value] = counts.get(next_phase.value, 0) + 1
            receipts = dict(current.receipt_digests)
            for name, digest in dict(receipt_digests or {}).items():
                existing = receipts.get(name)
                if existing is not None and existing != digest:
                    self._quarantine(run_id, reason_code="receipt_digest_drift")
                    raise RunnerAttemptQuarantined(
                        "runner_attempt_receipt_drift",
                        "runner attempt receipt digest is immutable",
                    )
                receipts[name] = digest
            updated = replace(
                current,
                phase=next_phase,
                state=next_state,
                effect_certainty=next_effect,
                retry_eligibility=next_retry,
                reconciliation_required=next_reconciliation,
                state_version=current.state_version + 1,
                phase_attempt_counts=counts,
                pre_effect_recovery_attempts_used=(
                    current.pre_effect_recovery_attempts_used
                    + (1 if consume_pre_effect_recovery else 0)
                ),
                transport_generation=next_generation,
                receipt_digests=receipts,
                safe_failure_code=safe_failure_code,
                updated_at=_now_iso(),
                journal_head_digest=None,
            )
            self._validate_transition(current, updated)
            return self._append(
                updated,
                event_type=event_type,
                reason_code=reason_code,
                previous_event_digest=current.journal_head_digest,
            )

    def authorize_pre_effect_recovery(
        self,
        run_id: str,
        spec: RunSpec,
        *,
        selected_mode: str,
        reason_code: str,
        failure_receipt: object,
    ) -> RunnerAttempt | None:
        with self._lock:
            attempt = self.load_bound(
                run_id,
                spec,
                selected_mode=selected_mode,
            )
            if (
                not self.transport_manager.enabled
                or attempt.state is not RunnerAttemptState.ACTIVE
                or attempt.effect_certainty is not RunnerEffectCertainty.NO_EFFECT
            ):
                return None
            if (
                attempt.pre_effect_recovery_attempts_used
                >= self.config.ssh_transport.pre_effect_recovery_attempts
            ):
                self.transition(
                    run_id,
                    retry_eligibility=RunnerRetryEligibility.TERMINAL,
                    safe_failure_code="pre_effect_recovery_exhausted",
                    receipt_digests={
                        f"transport_failure_v{attempt.state_version + 1}": (
                            receipt_digest(failure_receipt)
                        )
                    },
                    reason_code="pre_effect_recovery_exhausted",
                )
                return None
            expected_generation = attempt.transport_generation
            if expected_generation < 1:
                return None
            self.transport_manager.recovery_backoff(
                attempt.pre_effect_recovery_attempts_used
            )
            next_generation = self.transport_manager.replace_degraded_generation(
                expected_generation=expected_generation
            )
            return self.transition(
                run_id,
                transport_generation=next_generation,
                receipt_digests={
                    f"transport_failure_v{attempt.state_version + 1}": receipt_digest(
                        failure_receipt
                    )
                },
                increment_phase_attempt=True,
                consume_pre_effect_recovery=True,
                event_type="recovered",
                reason_code=reason_code,
                expected_state_version=attempt.state_version,
            )

    def authorize_restart_pre_effect_recovery(
        self,
        run_id: str,
        spec: RunSpec,
        *,
        selected_mode: str,
    ) -> RunnerAttempt | None:
        """Fence one same-run restart before payload dispatch."""

        with self._lock:
            attempt = self.load_bound(
                run_id,
                spec,
                selected_mode=selected_mode,
            )
            if (
                not self.transport_manager.enabled
                or attempt.state is not RunnerAttemptState.ACTIVE
                or attempt.effect_certainty is not RunnerEffectCertainty.NO_EFFECT
                or _PHASE_ORDER[attempt.phase]
                >= _PHASE_ORDER[RunnerAttemptPhase.DISPATCHING]
            ):
                return None
            receipt_name = f"process_restart_v{attempt.state_version + 1}"
            restart_receipt = {
                "schema_version": "runner_process_restart_recovery@1",
                "run_binding_digest": attempt.run_binding_digest,
                "state_version": attempt.state_version,
                "phase": attempt.phase.value,
                "effect_certainty": attempt.effect_certainty.value,
            }
            if (
                attempt.pre_effect_recovery_attempts_used
                >= self.config.ssh_transport.pre_effect_recovery_attempts
            ):
                return self.transition(
                    run_id,
                    phase=RunnerAttemptPhase.TERMINAL,
                    state=RunnerAttemptState.TERMINAL,
                    retry_eligibility=RunnerRetryEligibility.TERMINAL,
                    receipt_digests={
                        receipt_name: receipt_digest(restart_receipt)
                    },
                    safe_failure_code="pre_effect_recovery_exhausted",
                    event_type="recovered",
                    reason_code="process_restart_recovery_exhausted",
                    expected_state_version=attempt.state_version,
                )
            self.transport_manager.recovery_backoff(
                attempt.pre_effect_recovery_attempts_used
            )
            next_generation = self.transport_manager.ensure_recovery_generation(
                after_generation=attempt.transport_generation
            )
            return self.transition(
                run_id,
                transport_generation=next_generation,
                receipt_digests={receipt_name: receipt_digest(restart_receipt)},
                increment_phase_attempt=True,
                consume_pre_effect_recovery=True,
                event_type="recovered",
                reason_code="process_restart_pre_effect_recovered",
                expected_state_version=attempt.state_version,
            )

    def authorize_output_fetch_recovery(
        self,
        run_id: str,
        spec: RunSpec,
        *,
        selected_mode: str,
        failure_receipt: object,
    ) -> RunnerAttempt | None:
        """Authorize one effect-preserving fetch retry for a frozen run."""

        with self._lock:
            attempt = self.load_bound(
                run_id,
                spec,
                selected_mode=selected_mode,
            )
            if (
                not self.transport_manager.enabled
                or attempt.state is not RunnerAttemptState.ACTIVE
                or attempt.phase is not RunnerAttemptPhase.OUTPUTS_FETCHING
                or attempt.effect_certainty
                is not RunnerEffectCertainty.TERMINAL_KNOWN
                or attempt.retry_eligibility
                is not RunnerRetryEligibility.VERIFY_THEN_RETRY
            ):
                return None
            phase_attempts = attempt.phase_attempt_counts.get(
                RunnerAttemptPhase.OUTPUTS_FETCHING.value,
                0,
            )
            receipt_name = f"output_fetch_failure_v{attempt.state_version + 1}"
            if phase_attempts >= 2:
                self.transition(
                    run_id,
                    phase=RunnerAttemptPhase.TERMINAL,
                    state=RunnerAttemptState.TERMINAL,
                    retry_eligibility=RunnerRetryEligibility.TERMINAL,
                    safe_failure_code="output_fetch_recovery_exhausted",
                    receipt_digests={
                        receipt_name: receipt_digest(failure_receipt),
                    },
                    reason_code="output_fetch_recovery_exhausted",
                    expected_state_version=attempt.state_version,
                )
                return None
            if attempt.transport_generation < 1:
                return None
            self.transport_manager.recovery_backoff(0)
            next_generation = self.transport_manager.replace_degraded_generation(
                expected_generation=attempt.transport_generation
            )
            return self.transition(
                run_id,
                transport_generation=next_generation,
                receipt_digests={receipt_name: receipt_digest(failure_receipt)},
                increment_phase_attempt=True,
                event_type="recovered",
                reason_code="output_fetch_transport_recovered",
                expected_state_version=attempt.state_version,
            )

    def authorize_restart_output_fetch_recovery(
        self,
        run_id: str,
        spec: RunSpec,
        *,
        selected_mode: str,
    ) -> RunnerAttempt | None:
        """Resume only the fetch phase after a known terminal remote outcome."""

        with self._lock:
            attempt = self.load_bound(
                run_id,
                spec,
                selected_mode=selected_mode,
            )
            if (
                not self.transport_manager.enabled
                or attempt.state is not RunnerAttemptState.ACTIVE
                or attempt.phase is not RunnerAttemptPhase.OUTPUTS_FETCHING
                or attempt.effect_certainty
                is not RunnerEffectCertainty.TERMINAL_KNOWN
                or attempt.retry_eligibility
                is not RunnerRetryEligibility.VERIFY_THEN_RETRY
            ):
                return None
            phase_attempts = attempt.phase_attempt_counts.get(
                RunnerAttemptPhase.OUTPUTS_FETCHING.value,
                0,
            )
            restart_receipt = {
                "schema_version": "runner_output_fetch_restart_receipt@1",
                "run_binding_digest": attempt.run_binding_digest,
                "attempt_id": attempt.attempt_id,
                "prior_state_version": attempt.state_version,
                "prior_transport_generation": attempt.transport_generation,
            }
            receipt_name = f"output_fetch_restart_v{attempt.state_version + 1}"
            if phase_attempts >= 2:
                return self.transition(
                    run_id,
                    phase=RunnerAttemptPhase.TERMINAL,
                    state=RunnerAttemptState.TERMINAL,
                    retry_eligibility=RunnerRetryEligibility.TERMINAL,
                    safe_failure_code="output_fetch_recovery_exhausted",
                    receipt_digests={
                        receipt_name: receipt_digest(restart_receipt),
                    },
                    event_type="recovered",
                    reason_code="process_restart_output_fetch_exhausted",
                    expected_state_version=attempt.state_version,
                )
            if attempt.transport_generation < 1:
                return None
            self.transport_manager.recovery_backoff(0)
            next_generation = self.transport_manager.ensure_recovery_generation(
                after_generation=attempt.transport_generation
            )
            return self.transition(
                run_id,
                transport_generation=next_generation,
                receipt_digests={receipt_name: receipt_digest(restart_receipt)},
                increment_phase_attempt=True,
                event_type="recovered",
                reason_code="process_restart_output_fetch_recovered",
                expected_state_version=attempt.state_version,
            )

    def quarantine_output_conflict(
        self,
        run_id: str,
        spec: RunSpec,
        *,
        selected_mode: str,
        failure_receipt: object,
    ) -> RunnerAttempt:
        """Persist terminal evidence before closing a digest-invalid output."""

        with self._lock:
            attempt = self.load_bound(
                run_id,
                spec,
                selected_mode=selected_mode,
            )
            terminal = self.transition(
                run_id,
                phase=RunnerAttemptPhase.TERMINAL,
                state=RunnerAttemptState.QUARANTINED,
                effect_certainty=RunnerEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RunnerRetryEligibility.TERMINAL,
                reconciliation_required=False,
                safe_failure_code="output_contract_conflict",
                receipt_digests={
                    f"output_conflict_v{attempt.state_version + 1}": receipt_digest(
                        failure_receipt
                    )
                },
                reason_code="output_contract_conflict",
                expected_state_version=attempt.state_version,
            )
            self._quarantine(run_id, reason_code="output_contract_conflict")
            return terminal

    def terminalize_output_fetch_failure(
        self,
        run_id: str,
        spec: RunSpec,
        *,
        selected_mode: str,
        failure_receipt: object,
        safe_failure_code: str,
    ) -> RunnerAttempt:
        with self._lock:
            attempt = self.load_bound(
                run_id,
                spec,
                selected_mode=selected_mode,
            )
            if attempt.state is RunnerAttemptState.TERMINAL:
                return attempt
            return self.transition(
                run_id,
                phase=RunnerAttemptPhase.TERMINAL,
                state=RunnerAttemptState.TERMINAL,
                effect_certainty=RunnerEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RunnerRetryEligibility.TERMINAL,
                reconciliation_required=False,
                safe_failure_code=safe_failure_code,
                receipt_digests={
                    f"output_fetch_terminal_v{attempt.state_version + 1}": (
                        receipt_digest(failure_receipt)
                    )
                },
                reason_code=safe_failure_code,
                expected_state_version=attempt.state_version,
            )

    def audit_existing(self) -> tuple[dict[str, str], ...]:
        reports: list[dict[str, str]] = []
        for run_root in sorted(self.store.root.iterdir(), key=lambda path: path.name):
            if run_root.name == "cache" or not run_root.is_dir() or run_root.is_symlink():
                continue
            snapshot = run_root / "metadata" / _SNAPSHOT_NAME
            events = run_root / "metadata"
            if not snapshot.exists() and not (
                events.is_dir()
                and any(path.name.startswith(_EVENT_PREFIX) for path in events.iterdir())
            ):
                continue
            try:
                attempt = self.load(run_root.name)
            except RunnerAttemptQuarantined:
                reports.append({"run_id": run_root.name, "status": "quarantined"})
            else:
                reports.append(
                    {
                        "run_id": attempt.run_id,
                        "status": attempt.state.value,
                        "phase": attempt.phase.value,
                        "effect_certainty": attempt.effect_certainty.value,
                    }
                )
        return tuple(reports)

    def recover_interrupted_attempts(self) -> tuple[dict[str, str], ...]:
        recovered: list[dict[str, str]] = []
        for report in self.audit_existing():
            run_id = report["run_id"]
            if report["status"] == "quarantined":
                recovered.append(dict(report))
                continue
            try:
                raw_spec = self.store.read_json(run_id, "runspec.json")
                spec = RunSpec.from_dict(raw_spec)
                if spec.run_id != run_id:
                    raise ValueError("persisted RunSpec belongs to another run")
                unbound = self.load(run_id)
                attempt = self.load_bound(
                    run_id,
                    spec,
                    selected_mode=unbound.selected_mode,
                )
                if (
                    attempt.selected_mode == "sbatch"
                    and attempt.effect_certainty
                    in {
                        RunnerEffectCertainty.EFFECT_KNOWN,
                        RunnerEffectCertainty.TERMINAL_KNOWN,
                    }
                ):
                    handle = self.store.read_json(run_id, "job_handle.json")
                    if receipt_digest(handle) != attempt.receipt_digests.get(
                        "slurm_handle"
                    ):
                        raise ValueError("persisted Slurm handle receipt drifted")
            except RunnerAttemptQuarantined:
                recovered.append({"run_id": run_id, "status": "quarantined"})
                continue
            except Exception:  # noqa: BLE001 - private recovery evidence only.
                self._quarantine(run_id, reason_code="restart_binding_invalid")
                recovered.append({"run_id": run_id, "status": "quarantined"})
                continue
            if (
                attempt.state is RunnerAttemptState.ACTIVE
                and attempt.phase is RunnerAttemptPhase.DISPATCHING
            ):
                attempt = self.transition(
                    run_id,
                    state=RunnerAttemptState.RECONCILIATION_REQUIRED,
                    effect_certainty=RunnerEffectCertainty.DISPATCH_IN_DOUBT,
                    retry_eligibility=RunnerRetryEligibility.RECONCILE_REQUIRED,
                    reconciliation_required=True,
                    safe_failure_code="dispatch_in_doubt",
                    event_type="recovered",
                    reason_code="runner_interrupted_during_dispatch",
                )
            if attempt.state is RunnerAttemptState.RECONCILIATION_REQUIRED:
                disposition = "preserve_reconciliation_required"
            elif attempt.state in {
                RunnerAttemptState.TERMINAL,
                RunnerAttemptState.QUARANTINED,
            }:
                disposition = "terminal_evidence_only"
            elif (
                attempt.selected_mode == "sbatch"
                and attempt.effect_certainty
                in {
                    RunnerEffectCertainty.EFFECT_KNOWN,
                    RunnerEffectCertainty.TERMINAL_KNOWN,
                }
            ):
                disposition = "query_exact_handle"
            elif (
                attempt.effect_certainty is RunnerEffectCertainty.NO_EFFECT
                and _PHASE_ORDER[attempt.phase]
                < _PHASE_ORDER[RunnerAttemptPhase.DISPATCHING]
            ):
                disposition = "resume_same_run_pre_effect"
            elif (
                attempt.effect_certainty is RunnerEffectCertainty.TERMINAL_KNOWN
                and attempt.phase is RunnerAttemptPhase.OUTPUTS_FETCHING
            ):
                disposition = "resume_same_run_output_fetch"
            else:
                disposition = "preserve_verified_evidence"
            recovered.append(
                {
                    "run_id": run_id,
                    "status": attempt.state.value,
                    "phase": attempt.phase.value,
                    "effect_certainty": attempt.effect_certainty.value,
                    "disposition": disposition,
                }
            )
        return tuple(recovered)

    def record_shutdown_ambiguities(self) -> tuple[str, ...]:
        ambiguous: list[str] = []
        for report in self.audit_existing():
            if report["status"] == "quarantined":
                continue
            attempt = self.load(report["run_id"])
            if (
                attempt.state is RunnerAttemptState.ACTIVE
                and attempt.phase is RunnerAttemptPhase.DISPATCHING
            ):
                attempt = self.transition(
                    attempt.run_id,
                    state=RunnerAttemptState.RECONCILIATION_REQUIRED,
                    effect_certainty=RunnerEffectCertainty.DISPATCH_IN_DOUBT,
                    retry_eligibility=RunnerRetryEligibility.RECONCILE_REQUIRED,
                    reconciliation_required=True,
                    safe_failure_code="dispatch_in_doubt",
                    event_type="shutdown_observed",
                    reason_code="shutdown_during_dispatch",
                )
            if (
                attempt.state is RunnerAttemptState.RECONCILIATION_REQUIRED
                and attempt.selected_mode == "ssh"
            ):
                ambiguous.append(attempt.run_id)
        return tuple(sorted(ambiguous))

    def _append(
        self,
        attempt: RunnerAttempt,
        *,
        event_type: str,
        reason_code: str,
        previous_event_digest: str | None = None,
    ) -> RunnerAttempt:
        event = RunnerAttemptEvent.build(
            event_type=event_type,
            reason_code=reason_code,
            previous_event_digest=previous_event_digest,
            attempt=attempt,
        )
        event_name = f"{_EVENT_PREFIX}{attempt.state_version:09d}.json"
        self.store.write_json_once(attempt.run_id, event_name, event.to_dict())
        persisted = replace(attempt, journal_head_digest=event.event_digest)
        self.store.write_json(attempt.run_id, _SNAPSHOT_NAME, persisted.to_dict())
        return persisted

    def _load_verified(self, run_id: str) -> RunnerAttempt:
        paths = self.store.list_metadata(run_id, prefix=_EVENT_PREFIX)
        if not paths:
            raise ValueError("runner attempt event journal is missing")
        prior: RunnerAttempt | None = None
        prior_digest: str | None = None
        attempts_by_version: dict[int, RunnerAttempt] = {}
        for index, path in enumerate(paths, start=1):
            expected_name = f"{_EVENT_PREFIX}{index:09d}.json"
            if path.name != expected_name:
                raise ValueError("runner attempt event sequence is not contiguous")
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("runner attempt event must be an object")
            event = RunnerAttemptEvent.from_dict(raw)
            if event.previous_event_digest != prior_digest:
                raise ValueError("runner attempt event chain is broken")
            attempt = RunnerAttempt.from_dict(
                dict(event.attempt_snapshot),
                event_snapshot=True,
            )
            if attempt.run_id != run_id or attempt.state_version != index:
                raise ValueError("runner attempt event identity/version is invalid")
            if prior is not None:
                self._validate_transition(prior, attempt)
            prior = replace(attempt, journal_head_digest=event.event_digest)
            prior_digest = event.event_digest
            attempts_by_version[index] = prior
        assert prior is not None

        try:
            raw_snapshot = self.store.read_json(run_id, _SNAPSHOT_NAME)
        except FileNotFoundError:
            self.store.write_json(run_id, _SNAPSHOT_NAME, prior.to_dict())
            return prior
        snapshot = RunnerAttempt.from_dict(raw_snapshot)
        matching_event = attempts_by_version.get(snapshot.state_version)
        if matching_event is None or snapshot != matching_event:
            raise ValueError("runner attempt snapshot does not match its event")
        if snapshot.state_version < prior.state_version:
            self.store.write_json(run_id, _SNAPSHOT_NAME, prior.to_dict())
            return prior
        return snapshot

    @staticmethod
    def _validate_transition(current: RunnerAttempt, updated: RunnerAttempt) -> None:
        if current.immutable_identity != updated.immutable_identity:
            raise ValueError("runner attempt immutable identity changed")
        if updated.state_version != current.state_version + 1:
            raise ValueError("runner attempt state version is not monotonic")
        if updated.state not in _STATE_TRANSITIONS[current.state]:
            raise ValueError("runner attempt state transition is illegal")
        if _PHASE_ORDER[updated.phase] < _PHASE_ORDER[current.phase]:
            raise ValueError("runner attempt phase regressed")
        if _EFFECT_ORDER[updated.effect_certainty] < _EFFECT_ORDER[
            current.effect_certainty
        ]:
            raise ValueError("runner attempt effect certainty regressed")
        if updated.retry_eligibility not in _RETRY_TRANSITIONS[
            current.retry_eligibility
        ]:
            raise ValueError("runner attempt retry eligibility transition is illegal")
        if updated.transport_generation < current.transport_generation:
            raise ValueError("runner attempt transport generation regressed")
        recovery_delta = (
            updated.pre_effect_recovery_attempts_used
            - current.pre_effect_recovery_attempts_used
        )
        if recovery_delta not in {0, 1}:
            raise ValueError("runner attempt recovery counter is not monotonic")
        for name, digest in current.receipt_digests.items():
            if updated.receipt_digests.get(name) != digest:
                raise ValueError("runner attempt receipt digest changed or disappeared")

    def _quarantine(self, run_id: str, *, reason_code: str) -> None:
        try:
            self.store.write_json_once(
                run_id,
                _QUARANTINE_NAME,
                {
                    "schema_version": RUNNER_ATTEMPT_QUARANTINE_SCHEMA_VERSION,
                    "run_binding_digest": _binding_digest("run", {"run_id": run_id}),
                    "reason_code": reason_code,
                    "quarantined_at": _now_iso(),
                },
            )
        except FileExistsError:
            pass


def receipt_digest(value: object) -> str:
    return _binding_digest("private_receipt", value)


def runner_attempt_snapshot_path(store: ArtifactStore, run_id: str) -> Path:
    return store.run_root(run_id) / "metadata" / _SNAPSHOT_NAME
