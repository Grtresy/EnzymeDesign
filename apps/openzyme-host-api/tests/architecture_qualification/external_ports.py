from __future__ import annotations

from collections import defaultdict
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
import threading
from typing import Mapping

from openzyme_core import ControlledOperationResultArtifactRef
from openzyme_core import DurableRouteMaterializedResult
from openzyme_core import DurableRouteObservation
from openzyme_core import DurableRouteObservationKind
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperationDispatchRequest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import RetryEligibility
from openzyme_host_api.architecture_qualification import canonical_json_bytes


EFFECT_LEDGER_SCHEMA_ID = "openzyme_v3_qualification_effect_ledger@1"
QUALIFICATION_FIXTURE_MARKER = "qualification_fixture_non_cutover"
_MACHINE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_OBSERVATION_FIELDS = frozenset(
    {
        "backend_handle_ref",
        "effect_certainty",
        "error_code",
        "kind",
        "materialized_result",
        "retry_eligibility",
        "safe_receipt_digest",
        "safe_summary",
        "terminal_outcome",
    }
)
_MATERIALIZED_FIELDS = frozenset(
    {"artifact_refs", "bounded_result_envelope", "origin", "terminal_outcome"}
)
_ARTIFACT_REF_FIELDS = frozenset(
    {"artifact_digest", "artifact_id", "kind", "relative_path"}
)


class EffectAcceptance(StrEnum):
    NOT_ACCEPTED = "not_accepted"
    ACCEPTED = "accepted"
    IN_DOUBT = "in_doubt"
    TERMINAL = "terminal"


class ControlledExternalPortError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        acceptance: EffectAcceptance,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.acceptance = acceptance


@dataclass(frozen=True, slots=True)
class ControlledPortOutcome:
    acceptance: EffectAcceptance
    effect_attempted: bool = False
    response: Mapping[str, object] | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.error_code is not None and _MACHINE_ID.fullmatch(self.error_code) is None:
            raise ValueError("controlled port error_code must be a stable machine id")
        if self.acceptance is EffectAcceptance.NOT_ACCEPTED and self.response is not None:
            raise ValueError("not-accepted outcome cannot carry a response")
        if self.acceptance is EffectAcceptance.NOT_ACCEPTED and self.effect_attempted:
            raise ValueError("not-accepted outcome cannot record an effect attempt")
        if self.acceptance is EffectAcceptance.IN_DOUBT and self.response is not None:
            raise ValueError("in-doubt outcome cannot carry a terminal response")


def _closed_json(value: object) -> object:
    try:
        encoded = canonical_json_bytes(value)
    except Exception as exc:  # noqa: BLE001 - normalize fixture author errors
        raise ValueError("controlled port value is not canonical JSON") from exc
    return json.loads(encoded)


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


@dataclass(frozen=True, slots=True)
class EffectLedgerEntry:
    sequence: int
    port_id: str
    operation: str
    request: object
    request_digest: str
    acceptance: EffectAcceptance
    effect_attempted: bool
    response: object | None
    response_digest: str | None
    error_code: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptance": self.acceptance.value,
            "effect_attempted": self.effect_attempted,
            "error_code": self.error_code,
            "operation": self.operation,
            "port_id": self.port_id,
            "request": self.request,
            "request_digest": self.request_digest,
            "response": self.response,
            "response_digest": self.response_digest,
            "sequence": self.sequence,
        }


class ExternalEffectLedger:
    def __init__(self) -> None:
        self._entries: list[EffectLedgerEntry] = []
        self._lock = threading.Lock()

    def append(
        self,
        *,
        port_id: str,
        operation: str,
        request: object,
        outcome: ControlledPortOutcome,
    ) -> EffectLedgerEntry:
        normalized_request = _closed_json(request)
        normalized_response = (
            None if outcome.response is None else _closed_json(outcome.response)
        )
        with self._lock:
            entry = EffectLedgerEntry(
                sequence=len(self._entries) + 1,
                port_id=port_id,
                operation=operation,
                request=normalized_request,
                request_digest=_digest(normalized_request),
                acceptance=outcome.acceptance,
                effect_attempted=outcome.effect_attempted,
                response=normalized_response,
                response_digest=(
                    None
                    if normalized_response is None
                    else _digest(normalized_response)
                ),
                error_code=outcome.error_code,
            )
            self._entries.append(entry)
            return entry

    def entries(self) -> tuple[EffectLedgerEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    def count(
        self,
        *,
        port_id: str | None = None,
        operation: str | None = None,
        acceptance: EffectAcceptance | None = None,
    ) -> int:
        return sum(
            1
            for entry in self.entries()
            if (port_id is None or entry.port_id == port_id)
            and (operation is None or entry.operation == operation)
            and (acceptance is None or entry.acceptance is acceptance)
        )

    def snapshot(self) -> dict[str, object]:
        entries = [entry.to_dict() for entry in self.entries()]
        payload: dict[str, object] = {
            "entries": entries,
            "external_effects_real": False,
            "fixture_mode": QUALIFICATION_FIXTURE_MARKER,
            "schema_id": EFFECT_LEDGER_SCHEMA_ID,
        }
        return {
            **payload,
            "ledger_digest": _digest(payload),
        }

    def count_effects(self, *, port_id: str | None = None) -> int:
        return sum(
            1
            for entry in self.entries()
            if entry.effect_attempted
            and (port_id is None or entry.port_id == port_id)
        )


class ControlledExternalPort:
    qualification_fixture_non_cutover = True

    def __init__(self, *, port_id: str, ledger: ExternalEffectLedger) -> None:
        if _MACHINE_ID.fullmatch(port_id) is None:
            raise ValueError("controlled port_id must be a stable machine id")
        self.port_id = port_id
        self.ledger = ledger
        self._plans: dict[str, deque[ControlledPortOutcome]] = defaultdict(deque)
        self._barriers: dict[str, tuple[threading.Event, threading.Event]] = {}
        self._lock = threading.Lock()

    def queue(self, operation: str, *outcomes: ControlledPortOutcome) -> None:
        if _MACHINE_ID.fullmatch(operation) is None:
            raise ValueError("controlled operation must be a stable machine id")
        if not outcomes:
            raise ValueError("controlled port plan must not be empty")
        with self._lock:
            self._plans[operation].extend(outcomes)

    def install_one_shot_barrier(
        self,
        operation: str,
        *,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        """Pause one controlled call at its external boundary for race scenarios."""

        if _MACHINE_ID.fullmatch(operation) is None:
            raise ValueError("controlled operation must be a stable machine id")
        with self._lock:
            if operation in self._barriers:
                raise ValueError("controlled port barrier is already installed")
            self._barriers[operation] = (entered, release)

    def invoke(self, operation: str, request: Mapping[str, object]) -> dict[str, object]:
        if _MACHINE_ID.fullmatch(operation) is None:
            raise ValueError("controlled operation must be a stable machine id")
        with self._lock:
            plan = self._plans.get(operation)
            outcome = None if not plan else plan.popleft()
            barrier = self._barriers.pop(operation, None)
        if barrier is not None:
            entered, release = barrier
            entered.set()
            if not release.wait(timeout=10.0):
                raise ControlledExternalPortError(
                    "controlled port barrier exceeded its local deadline",
                    error_code="qualification_external_barrier_timeout",
                    acceptance=EffectAcceptance.NOT_ACCEPTED,
                )
        if outcome is None:
            outcome = ControlledPortOutcome(
                acceptance=EffectAcceptance.NOT_ACCEPTED,
                error_code="qualification_external_port_unplanned",
            )
        self.ledger.append(
            port_id=self.port_id,
            operation=operation,
            request=request,
            outcome=outcome,
        )
        if outcome.error_code is not None:
            raise ControlledExternalPortError(
                f"controlled port {self.port_id!r} returned {outcome.error_code!r}",
                error_code=outcome.error_code,
                acceptance=outcome.acceptance,
            )
        if outcome.acceptance is EffectAcceptance.IN_DOUBT:
            raise ControlledExternalPortError(
                f"controlled port {self.port_id!r} outcome is in doubt",
                error_code="qualification_external_outcome_in_doubt",
                acceptance=outcome.acceptance,
            )
        if outcome.response is None:
            raise ControlledExternalPortError(
                f"controlled port {self.port_id!r} has no terminal response",
                error_code="qualification_external_response_missing",
                acceptance=outcome.acceptance,
            )
        normalized = _closed_json(outcome.response)
        if not isinstance(normalized, dict):
            raise ControlledExternalPortError(
                f"controlled port {self.port_id!r} response is not an object",
                error_code="qualification_external_response_invalid",
                acceptance=outcome.acceptance,
            )
        return normalized


@dataclass(frozen=True, slots=True)
class QualificationDurableRouteAdapter:
    port: ControlledExternalPort
    route_policy_id: str = "qualification.controlled:v1"
    selected_backend: str = "qualification_controlled"
    adapter_policy_id: str = "qualification_controlled_adapter:v1"
    qualification_fixture_non_cutover: bool = True

    def prepare_dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> str:
        identity = canonical_json_bytes(
            {
                "dispatch_generation": execution.dispatch_generation,
                "execution_id": execution.execution_id,
                "request_digest": request.request_digest,
            }
        )
        return "qualification://" + hashlib.sha256(identity).hexdigest()

    def dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self._invoke("dispatch", execution, request)

    def poll(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self._invoke("poll", execution, request)

    def reconcile(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self._invoke("reconcile", execution, request)

    def materialize(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self._invoke("materialize", execution, request)

    def _invoke(
        self,
        operation: str,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        response = self.port.invoke(
            operation,
            {
                "backend_handle_ref": execution.backend_handle_ref,
                "dispatch_generation": execution.dispatch_generation,
                "execution_id": execution.execution_id,
                "operation_id": execution.operation_id,
                "request_digest": request.request_digest,
                "route_policy_id": execution.route_policy_id,
                "session_id": execution.session_id,
            },
        )
        return self._observation(response, execution=execution)

    @staticmethod
    def _observation(
        response: Mapping[str, object],
        *,
        execution: ControlledOperationExecution,
    ) -> DurableRouteObservation:
        if set(response) != _OBSERVATION_FIELDS:
            raise ControlledExternalPortError(
                "controlled durable response is not a closed observation",
                error_code="qualification_durable_observation_invalid",
                acceptance=EffectAcceptance.TERMINAL,
            )
        try:
            kind = DurableRouteObservationKind(str(response["kind"]))
            effect_certainty = ExternalEffectCertainty(
                str(response["effect_certainty"])
            )
            retry_eligibility = RetryEligibility(str(response["retry_eligibility"]))
            terminal_outcome = (
                None
                if response["terminal_outcome"] is None
                else ControlledOperationExecutionTerminalOutcome(
                    str(response["terminal_outcome"])
                )
            )
        except ValueError as exc:
            raise ControlledExternalPortError(
                "controlled durable response contains an unknown enum",
                error_code="qualification_durable_observation_invalid",
                acceptance=EffectAcceptance.TERMINAL,
            ) from exc
        backend_handle_ref = response["backend_handle_ref"]
        if backend_handle_ref is not None and backend_handle_ref != (
            execution.backend_handle_ref
        ):
            raise ControlledExternalPortError(
                "controlled durable response changed the backend handle",
                error_code="qualification_durable_observation_identity_drift",
                acceptance=EffectAcceptance.TERMINAL,
            )
        materialized = response["materialized_result"]
        materialized_result = None
        if materialized is not None:
            materialized_result = QualificationDurableRouteAdapter._materialized_result(
                materialized
            )
        for field in ("safe_receipt_digest", "safe_summary", "error_code"):
            if response[field] is not None and not isinstance(response[field], str):
                raise ControlledExternalPortError(
                    "controlled durable response contains invalid optional text",
                    error_code="qualification_durable_observation_invalid",
                    acceptance=EffectAcceptance.TERMINAL,
                )
        return DurableRouteObservation(
            kind=kind,
            effect_certainty=effect_certainty,
            retry_eligibility=retry_eligibility,
            backend_handle_ref=(
                None if backend_handle_ref is None else str(backend_handle_ref)
            ),
            safe_receipt_digest=(
                None
                if response["safe_receipt_digest"] is None
                else str(response["safe_receipt_digest"])
            ),
            safe_summary=(
                None
                if response["safe_summary"] is None
                else str(response["safe_summary"])
            ),
            error_code=(
                None
                if response["error_code"] is None
                else str(response["error_code"])
            ),
            terminal_outcome=terminal_outcome,
            materialized_result=materialized_result,
        )

    @staticmethod
    def _materialized_result(value: object) -> DurableRouteMaterializedResult:
        if not isinstance(value, dict) or set(value) != _MATERIALIZED_FIELDS:
            raise ControlledExternalPortError(
                "controlled materialized result is not closed",
                error_code="qualification_durable_materialized_result_invalid",
                acceptance=EffectAcceptance.TERMINAL,
            )
        envelope = value["bounded_result_envelope"]
        refs = value["artifact_refs"]
        origin = value["origin"]
        if not isinstance(envelope, dict) or not isinstance(refs, list) or not isinstance(
            origin, str
        ):
            raise ControlledExternalPortError(
                "controlled materialized result has invalid fields",
                error_code="qualification_durable_materialized_result_invalid",
                acceptance=EffectAcceptance.TERMINAL,
            )
        artifact_refs: list[ControlledOperationResultArtifactRef] = []
        try:
            for raw_ref in refs:
                if not isinstance(raw_ref, dict) or set(raw_ref) != _ARTIFACT_REF_FIELDS:
                    raise ValueError("artifact ref is not closed")
                artifact_refs.append(
                    ControlledOperationResultArtifactRef(
                        artifact_id=str(raw_ref["artifact_id"]),
                        kind=ArtifactKind(str(raw_ref["kind"])),
                        relative_path=str(raw_ref["relative_path"]),
                        artifact_digest=str(raw_ref["artifact_digest"]),
                    )
                )
            terminal_outcome = ControlledOperationExecutionTerminalOutcome(
                str(value["terminal_outcome"])
            )
        except (TypeError, ValueError) as exc:
            raise ControlledExternalPortError(
                "controlled materialized result identity is invalid",
                error_code="qualification_durable_materialized_result_invalid",
                acceptance=EffectAcceptance.TERMINAL,
            ) from exc
        normalized_refs = tuple(artifact_refs)
        return DurableRouteMaterializedResult(
            bounded_result_envelope=dict(envelope),
            artifact_set_digest=controlled_operation_artifact_set_digest(
                normalized_refs
            ),
            origin=origin,
            artifact_refs=normalized_refs,
            terminal_outcome=terminal_outcome,
        )


__all__ = [
    "ControlledExternalPort",
    "ControlledExternalPortError",
    "ControlledPortOutcome",
    "EFFECT_LEDGER_SCHEMA_ID",
    "EffectAcceptance",
    "EffectLedgerEntry",
    "ExternalEffectLedger",
    "QualificationDurableRouteAdapter",
    "QUALIFICATION_FIXTURE_MARKER",
]
