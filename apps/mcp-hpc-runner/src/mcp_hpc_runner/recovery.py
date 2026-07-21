from __future__ import annotations

from enum import StrEnum

from .remote import CommandResult


class PreEffectFailureClass(StrEnum):
    AUTHENTICATED_TRANSPORT = "authenticated_transport"
    DETERMINISTIC_COMMAND = "deterministic_command"


class DirectDispatchObservation(StrEnum):
    NOT_ACCEPTED = "not_accepted"
    DISPATCH_IN_DOUBT = "dispatch_in_doubt"
    TERMINAL_OBSERVED = "terminal_observed"


_RSYNC_TRANSPORT_CODES = frozenset({10, 11, 12, 30, 35, 255})


def classify_pre_effect_failure(result: CommandResult) -> PreEffectFailureClass:
    if result.timed_out or not result.process_started or result.returncode == 255:
        return PreEffectFailureClass.AUTHENTICATED_TRANSPORT
    executable = result.args[0] if result.args else ""
    if executable == "rsync" and result.returncode in _RSYNC_TRANSPORT_CODES:
        return PreEffectFailureClass.AUTHENTICATED_TRANSPORT
    return PreEffectFailureClass.DETERMINISTIC_COMMAND


def classify_direct_dispatch(result: CommandResult) -> DirectDispatchObservation:
    if not result.process_started:
        return DirectDispatchObservation.NOT_ACCEPTED
    if result.timed_out or result.returncode == 255:
        return DirectDispatchObservation.DISPATCH_IN_DOUBT
    return DirectDispatchObservation.TERMINAL_OBSERVED


def safe_transport_failure_receipt(
    result: CommandResult,
    *,
    phase: str,
) -> dict[str, object]:
    return {
        "schema_version": "runner_transport_failure@1",
        "phase": phase,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "process_started": result.process_started,
        "elapsed_seconds": round(result.elapsed_seconds, 6),
        "failure_class": classify_pre_effect_failure(result).value,
    }
