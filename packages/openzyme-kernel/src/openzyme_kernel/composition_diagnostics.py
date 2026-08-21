from __future__ import annotations

from dataclasses import dataclass
import re
import traceback
from typing import Any

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureObservation
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import PrivateDiagnosticRecord
from openzyme_contracts import RetryEligibility
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier

from .errors import KernelContractError


_SAFE_DETAIL_KEYS = frozenset(
    {
        "component_id",
        "plugin_id",
        "plugin_ids",
        "driver_id",
        "route_id",
        "route_ids",
        "route_key",
        "tool_name",
        "contribution_id",
        "state_namespace",
        "selection_key",
        "surface",
        "surface_kind",
        "verification_kind",
        "expected_digest",
        "observed_digest",
        "expected_manifest_digest",
        "observed_manifest_digest",
        "active_epoch_id",
        "requested_epoch_id",
        "epoch_id",
        "distribution_id",
        "session_id",
        "drifted_fields",
        "missing_kinds",
        "unexpected_kinds",
        "missing_ids",
        "unexpected_ids",
        "missing_port_contracts",
        "capability_id",
        "provider_plugin_ids",
        "cycle",
        "target_id",
        "action",
    }
)
_SECRET_KEY = re.compile(
    r"(?:secret|password|passwd|token|credential|private[_-]?key|api[_-]?key)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CompositionFailureContext:
    failure_id: str
    distribution_id: str
    component_id: str
    phase: str
    source_ref: str
    source_version: str
    correlation_id: str
    created_at: str
    session_id: str = "deployment"

    def __post_init__(self) -> None:
        for field_name in (
            "failure_id",
            "distribution_id",
            "component_id",
            "phase",
            "source_ref",
            "source_version",
            "correlation_id",
            "session_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if not isinstance(self.created_at, str) or not self.created_at:
            raise ValueError("created_at must be a non-empty instant")


@dataclass(frozen=True, slots=True)
class CompositionFailureRecords:
    public: FailureObservation
    private: PrivateDiagnosticRecord


def observe_composition_failure(
    error: BaseException,
    *,
    context: CompositionFailureContext,
) -> CompositionFailureRecords:
    error_code = (
        error.code
        if isinstance(error, KernelContractError)
        else "composition_activation_internal_error"
    )
    details = error.details if isinstance(error, KernelContractError) else {}
    diagnostic_id = _diagnostic_id(context, error_code)
    cause_chain = _public_cause_chain(error)
    private = PrivateDiagnosticRecord.create(
        diagnostic_id=diagnostic_id,
        failure_id=context.failure_id,
        session_id=context.session_id,
        component=context.component_id,
        operation="activate_composition",
        phase=context.phase,
        exception_type=type(error).__name__[:256],
        exception_message=str(error)[:8192],
        traceback_text="".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )[:65536],
        cause_chain=_private_cause_chain(error),
        errno=getattr(error, "errno", None),
        return_code=getattr(error, "returncode", None),
        bounded_stdout=_bounded_text(getattr(error, "stdout", None)),
        bounded_stderr=_bounded_text(getattr(error, "stderr", None)),
        private_context=_private_context(details),
        source_kind="composition_activation",
        source_ref=context.source_ref,
        source_version=context.source_version,
        correlation_id=context.correlation_id,
        created_at=context.created_at,
    )
    public = FailureObservation(
        failure_id=context.failure_id,
        session_id=context.session_id,
        source_kind="composition_activation",
        source_ref=context.source_ref,
        source_version=context.source_version,
        phase=context.phase,
        failure_class=FailureClass.SYSTEM,
        recoverability=FailureRecoverability.TERMINAL,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.HARNESS,
        error_code=error_code,
        safe_summary="Deployment composition activation failed before surfaces were enabled.",
        facts=_public_facts(details),
        likely_causes=(
            "The selected composition, installed component, schema or catalog identity did not verify.",
        ),
        evidence_refs=(),
        created_at=context.created_at,
        safe_hint="Repair the exact composition inputs and start a new offline activation attempt.",
        private_diagnostic_digest=private.record_digest,
        component=context.component_id,
        operation="activate_composition",
        identities={
            "distribution_id": context.distribution_id,
            "source_ref": context.source_ref,
            "source_version": context.source_version,
            "correlation_id": context.correlation_id,
        },
        mutation_applied=False,
        fallback_performed=False,
        cause_chain=cause_chain,
        diagnostic_id=diagnostic_id,
        next_action="repair_composition_and_restart",
    )
    return CompositionFailureRecords(public=public, private=private)


def _diagnostic_id(context: CompositionFailureContext, error_code: str) -> str:
    suffix = canonical_sha256_digest(
        {
            "failure_id": context.failure_id,
            "distribution_id": context.distribution_id,
            "source_version": context.source_version,
            "error_code": error_code,
        }
    ).removeprefix("sha256:")[:24]
    return f"diagnostic_{suffix}"


def _public_facts(details: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for key, value in details.items():
        if key not in _SAFE_DETAIL_KEYS or _SECRET_KEY.search(key):
            continue
        safe = _safe_public_value(value)
        if safe is not None:
            facts[key] = safe
    return dict(sorted(facts.items()))


def _safe_public_value(value: Any) -> Any | None:
    if isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        if not value or len(value) > 512 or value.startswith(("/", "\\")):
            return None
        return value
    if isinstance(value, list | tuple):
        safe_items = [_safe_public_value(item) for item in value[:64]]
        if any(item is None for item in safe_items):
            return None
        return safe_items
    return None


def _private_context(details: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key, value in details.items():
        if _SECRET_KEY.search(str(key)):
            context[str(key)] = "[redacted]"
        else:
            context[str(key)] = _bounded_private_value(value)
    return context


def _bounded_private_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:4096]
    if isinstance(value, dict):
        return {
            str(key)[:256]: (
                "[redacted]"
                if _SECRET_KEY.search(str(key))
                else _bounded_private_value(item)
            )
            for key, item in list(value.items())[:128]
        }
    if isinstance(value, list | tuple):
        return [_bounded_private_value(item) for item in value[:128]]
    return repr(value)[:4096]


def _public_cause_chain(error: BaseException) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "type": type(item).__name__,
            "code": (
                item.code
                if isinstance(item, KernelContractError)
                else "internal_cause"
            ),
            "message_digest": canonical_sha256_digest({"message": str(item)}),
        }
        for item in _walk_causes(error)
    )


def _private_cause_chain(error: BaseException) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "type": type(item).__name__[:256],
            "code": (
                item.code
                if isinstance(item, KernelContractError)
                else "internal_cause"
            ),
            "message": str(item)[:8192],
        }
        for item in _walk_causes(error)
    )


def _walk_causes(error: BaseException) -> tuple[BaseException, ...]:
    causes: list[BaseException] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(causes) < 8:
        causes.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return tuple(causes)


def _bounded_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[:16384]
    return str(value)[:16384]


__all__ = [
    "CompositionFailureContext",
    "CompositionFailureRecords",
    "observe_composition_failure",
]
