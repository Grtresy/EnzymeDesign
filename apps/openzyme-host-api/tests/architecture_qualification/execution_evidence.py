from __future__ import annotations

import hashlib
import threading
from typing import Mapping

from openzyme_host_api.architecture_qualification import canonical_json_bytes


_LOCK = threading.Lock()
_OBSERVATION_DIGESTS: list[str] = []
_EFFECT_LEDGER_DIGESTS: list[str] = []
_OBSERVED_P0_TRIGGER_IDS: list[str] = []


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def record_observation_evidence(
    *,
    observation_digest: str,
    effect_ledger: Mapping[str, object],
) -> None:
    record_effect_ledger_snapshot(effect_ledger)
    with _LOCK:
        _append_once(_OBSERVATION_DIGESTS, observation_digest)


def record_execution_observation_digest(observation_digest: str) -> None:
    if not observation_digest:
        raise ValueError("execution observation digest must not be empty")
    with _LOCK:
        _append_once(_OBSERVATION_DIGESTS, observation_digest)


def record_effect_ledger_snapshot(snapshot: Mapping[str, object]) -> None:
    if snapshot.get("external_effects_real") is not False:
        raise AssertionError("qualification evidence recorded a real external effect")
    ledger_digest = snapshot.get("ledger_digest")
    if not isinstance(ledger_digest, str):
        raise AssertionError("qualification effect ledger digest is absent")
    payload = {key: value for key, value in snapshot.items() if key != "ledger_digest"}
    if ledger_digest != _digest(payload):
        raise AssertionError("qualification effect ledger digest drifted")
    with _LOCK:
        _append_once(_EFFECT_LEDGER_DIGESTS, ledger_digest)


def execution_evidence_snapshot() -> dict[str, object]:
    with _LOCK:
        return {
            "effect_ledger_digests": sorted(_EFFECT_LEDGER_DIGESTS),
            "external_effects_real": False,
            "observation_digests": sorted(_OBSERVATION_DIGESTS),
            "observed_p0_trigger_ids": sorted(_OBSERVED_P0_TRIGGER_IDS),
            "schema_id": "openzyme_v3_architecture_execution_evidence@1",
        }


def record_observed_p0_trigger(trigger_id: str) -> None:
    if not trigger_id:
        raise ValueError("observed P0 trigger id must not be empty")
    with _LOCK:
        _append_once(_OBSERVED_P0_TRIGGER_IDS, trigger_id)


__all__ = [
    "execution_evidence_snapshot",
    "record_execution_observation_digest",
    "record_effect_ledger_snapshot",
    "record_observation_evidence",
    "record_observed_p0_trigger",
]
