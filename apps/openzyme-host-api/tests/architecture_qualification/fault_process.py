from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import selectors
import signal
import subprocess
import sys
import time

from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_api.architecture_qualification import (
    canonical_json_document_bytes,
)

from .external_ports import ExternalEffectLedger
from .safety import QualificationSafetyGuard
from .safety import scrubbed_environment


FAULT_PROCESS_PORT_ID = "qualification.fault_process"
FAULT_READY_SCHEMA_ID = "openzyme_v3_qualification_fault_ready@1"
FAULT_EVIDENCE_SCHEMA_ID = "openzyme_v3_qualification_fault_evidence@1"
FAULT_CHILD_MODES = frozenset(
    {
        "descendant_residue",
        "early_exit",
        "host_dispatch_in_doubt",
        "ignore_term",
        "sanitize_long_scalar",
        "wait",
    }
)
_CONTROL_FD_ENV = "OPENZYME_QUALIFICATION_CONTROL_FD"
_LAUNCH_NONCE_ENV = "OPENZYME_QUALIFICATION_LAUNCH_NONCE"
_SCENARIO_ROOT_ENV = "OPENZYME_QUALIFICATION_SCENARIO_ROOT"
_READY_FIELDS = frozenset(
    {
        "child_pgid",
        "child_pid",
        "child_start_time_ticks",
        "frame_digest",
        "launch_nonce",
        "mode",
        "payload",
        "schema_id",
    }
)
_MAX_READY_BYTES = 64 * 1024


class FaultProcessProtocolError(RuntimeError):
    code = "architecture_qualification_fault_process_invalid"


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _process_start_time_ticks(pid: int) -> int:
    content = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    close = content.rfind(")")
    if close < 0:
        raise ValueError("process stat comm terminator is absent")
    fields = content[close + 2 :].split()
    if len(fields) < 20:
        raise ValueError("process stat is truncated")
    return int(fields[19])


def _process_group_members(pgid: int) -> tuple[int, ...]:
    members: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            content = (entry / "stat").read_text(encoding="utf-8")
            close = content.rfind(")")
            fields = content[close + 2 :].split()
            state = fields[0]
            process_group = int(fields[2])
        except (OSError, ValueError, IndexError):
            continue
        if process_group == pgid and state != "Z":
            members.append(int(entry.name))
    return tuple(sorted(members))


def build_fault_ready_frame(
    *,
    mode: str,
    launch_nonce: str,
    payload: Mapping[str, object],
) -> bytes:
    if mode not in FAULT_CHILD_MODES:
        raise FaultProcessProtocolError("fault child mode is unsupported")
    child_pid = os.getpid()
    material: dict[str, object] = {
        "child_pgid": os.getpgrp(),
        "child_pid": child_pid,
        "child_start_time_ticks": _process_start_time_ticks(child_pid),
        "launch_nonce": launch_nonce,
        "mode": mode,
        "payload": dict(payload),
        "schema_id": FAULT_READY_SCHEMA_ID,
    }
    return canonical_json_document_bytes(
        {**material, "frame_digest": _digest(material)}
    )


def _read_ready_frame(
    descriptor: int,
    *,
    process: subprocess.Popen[bytes],
    timeout_seconds: float,
) -> bytes:
    selector = selectors.DefaultSelector()
    selector.register(descriptor, selectors.EVENT_READ)
    content = bytearray()
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            events = selector.select(timeout=min(0.05, remaining))
            if events:
                chunk = os.read(descriptor, _MAX_READY_BYTES + 1 - len(content))
                if chunk:
                    content.extend(chunk)
                    if len(content) > _MAX_READY_BYTES:
                        raise FaultProcessProtocolError(
                            "fault child ready frame is oversized"
                        )
                    if content.endswith(b"\n"):
                        return bytes(content)
                elif content:
                    break
            if process.poll() is not None and not events:
                continue
    finally:
        selector.close()
    raise FaultProcessProtocolError("fault child did not emit one bounded ready frame")


def _validate_ready_frame(
    content: bytes,
    *,
    process: subprocess.Popen[bytes],
    mode: str,
    launch_nonce: str,
) -> tuple["FaultProcessIdentity", dict[str, object], str]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaultProcessProtocolError("fault child ready frame is not JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) != _READY_FIELDS
        or canonical_json_document_bytes(value) != content
    ):
        raise FaultProcessProtocolError(
            "fault child ready frame is not closed canonical JSON"
        )
    material = {key: item for key, item in value.items() if key != "frame_digest"}
    if (
        value.get("schema_id") != FAULT_READY_SCHEMA_ID
        or value.get("mode") != mode
        or value.get("launch_nonce") != launch_nonce
        or value.get("frame_digest") != _digest(material)
    ):
        raise FaultProcessProtocolError("fault child ready frame identity drifted")
    payload = value.get("payload")
    if not isinstance(payload, dict) or payload.get("credential_names") != []:
        credential_names = (
            None if not isinstance(payload, dict) else payload.get("credential_names")
        )
        raise FaultProcessProtocolError(
            "fault child did not prove a credential-free environment; "
            f"credential_names={credential_names!r}"
        )
    integer_values = (
        value.get("child_pid"),
        value.get("child_pgid"),
        value.get("child_start_time_ticks"),
    )
    if any(
        not isinstance(item, int) or isinstance(item, bool) or item <= 0
        for item in integer_values
    ):
        raise FaultProcessProtocolError("fault child process identity is invalid")
    identity = FaultProcessIdentity(
        pid=int(value["child_pid"]),
        pgid=int(value["child_pgid"]),
        start_time_ticks=int(value["child_start_time_ticks"]),
    )
    try:
        observed_pgid = os.getpgid(process.pid)
        observed_start = _process_start_time_ticks(process.pid)
    except (OSError, ValueError) as exc:
        raise FaultProcessProtocolError(
            "fault child process identity disappeared before validation"
        ) from exc
    if (
        process.pid != identity.pid
        or identity.pgid != identity.pid
        or observed_pgid != identity.pgid
        or observed_start != identity.start_time_ticks
    ):
        raise FaultProcessProtocolError("fault child process identity is unproven")
    return identity, dict(payload), str(value["frame_digest"])


def _wait_for_retirement(
    process: subprocess.Popen[bytes],
    *,
    pgid: int,
    timeout_seconds: float,
) -> tuple[int, ...]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        process.poll()
        members = _process_group_members(pgid)
        if process.returncode is not None and not members:
            return ()
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    process.poll()
    return _process_group_members(pgid)


@dataclass(frozen=True, slots=True)
class FaultProcessIdentity:
    pid: int
    pgid: int
    start_time_ticks: int

    def to_dict(self) -> dict[str, int]:
        return {
            "pgid": self.pgid,
            "pid": self.pid,
            "start_time_ticks": self.start_time_ticks,
        }


@dataclass(frozen=True, slots=True)
class FaultProcessEvidence:
    payload: Mapping[str, object]
    evidence_digest: str

    def to_dict(self) -> dict[str, object]:
        return {**dict(self.payload), "evidence_digest": self.evidence_digest}


@dataclass(frozen=True, slots=True)
class RetirementSemantics:
    cutover_eligible: bool
    external_outcome: str
    quarantine_required: bool
    raw_signal: int | None
    retirement_proven: bool


def evaluate_retirement_semantics(
    *,
    identity_exact: bool,
    raw_exit_code: int | None,
    final_group_member_count: int,
    force_retirement_unproven: bool = False,
) -> RetirementSemantics:
    """Purely derive claims from sealed process identity and containment facts."""

    if final_group_member_count < 0:
        raise ValueError("final group member count must not be negative")
    retirement_proven = (
        identity_exact
        and raw_exit_code is not None
        and final_group_member_count == 0
        and not force_retirement_unproven
    )
    return RetirementSemantics(
        cutover_eligible=False,
        external_outcome="unknown",
        quarantine_required=not retirement_proven,
        raw_signal=(
            -raw_exit_code
            if isinstance(raw_exit_code, int) and raw_exit_code < 0
            else None
        ),
        retirement_proven=retirement_proven,
    )


@dataclass(slots=True)
class IdentityBoundFaultProcessHandle:
    process: subprocess.Popen[bytes]
    identity: FaultProcessIdentity
    mode: str
    ready_payload: Mapping[str, object]
    ready_frame_digest: str
    operator_grace_seconds: float
    term_grace_seconds: float
    kill_grace_seconds: float
    deadline_seconds: float
    retirement_calls: int = 0
    _evidence: FaultProcessEvidence | None = None

    def retire(
        self,
        *,
        operator_signal: signal.Signals | None,
        expected_identity: FaultProcessIdentity | None = None,
        force_retirement_unproven: bool = False,
    ) -> FaultProcessEvidence:
        self.retirement_calls += 1
        if self._evidence is not None:
            return self._evidence
        expected = self.identity if expected_identity is None else expected_identity
        identity_exact = expected == self.identity
        initial_exit_code = self.process.poll()
        initial_members = _process_group_members(self.identity.pgid)
        if identity_exact and initial_exit_code is None:
            try:
                identity_exact = (
                    os.getpgid(self.identity.pid) == self.identity.pgid
                    and _process_start_time_ticks(self.identity.pid)
                    == self.identity.start_time_ticks
                )
            except (OSError, ValueError):
                identity_exact = False
        phases: list[dict[str, object]] = [
            {
                "group_member_count": len(initial_members),
                "identity_exact": identity_exact,
                "phase": "identity_observation",
                "sent": False,
                "signal": None,
            }
        ]
        descendant_residue_observed = (
            initial_exit_code is not None and bool(initial_members)
        )

        if operator_signal is None:
            deadline = time.monotonic() + self.deadline_seconds
            while self.process.poll() is None and time.monotonic() < deadline:
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            phases.append(
                {
                    "group_member_count": len(
                        _process_group_members(self.identity.pgid)
                    ),
                    "identity_exact": identity_exact,
                    "phase": "deadline",
                    "sent": False,
                    "signal": None,
                }
            )
        else:
            sent = False
            if identity_exact and _process_group_members(self.identity.pgid):
                try:
                    os.killpg(self.identity.pgid, operator_signal)
                    sent = True
                except ProcessLookupError:
                    pass
            phases.append(
                {
                    "group_member_count": len(initial_members),
                    "identity_exact": identity_exact,
                    "phase": "operator_signal",
                    "sent": sent,
                    "signal": int(operator_signal),
                }
            )
            _wait_for_retirement(
                self.process,
                pgid=self.identity.pgid,
                timeout_seconds=self.operator_grace_seconds,
            )

        remaining = _process_group_members(self.identity.pgid)
        term_sent = False
        if identity_exact and remaining and operator_signal is not signal.SIGTERM:
            try:
                os.killpg(self.identity.pgid, signal.SIGTERM)
                term_sent = True
            except ProcessLookupError:
                pass
        elif not identity_exact and self.process.poll() is None:
            self.process.terminate()
            term_sent = True
        phases.append(
            {
                "group_member_count": len(remaining),
                "identity_exact": identity_exact,
                "phase": "sigterm",
                "sent": term_sent,
                "signal": int(signal.SIGTERM),
            }
        )
        remaining = _wait_for_retirement(
            self.process,
            pgid=self.identity.pgid,
            timeout_seconds=self.term_grace_seconds,
        )
        kill_sent = False
        if identity_exact and remaining:
            try:
                os.killpg(self.identity.pgid, signal.SIGKILL)
                kill_sent = True
            except ProcessLookupError:
                pass
        elif not identity_exact and self.process.poll() is None:
            self.process.kill()
            kill_sent = True
        phases.append(
            {
                "group_member_count": len(remaining),
                "identity_exact": identity_exact,
                "phase": "sigkill",
                "sent": kill_sent,
                "signal": int(signal.SIGKILL),
            }
        )
        final_members = _wait_for_retirement(
            self.process,
            pgid=self.identity.pgid,
            timeout_seconds=self.kill_grace_seconds,
        )
        try:
            self.process.wait(timeout=0)
        except subprocess.TimeoutExpired:
            pass
        if self.process.stderr is not None:
            self.process.stderr.close()
        raw_exit_code = self.process.returncode
        semantics = evaluate_retirement_semantics(
            identity_exact=identity_exact,
            raw_exit_code=raw_exit_code,
            final_group_member_count=len(final_members),
            force_retirement_unproven=force_retirement_unproven,
        )
        phases.append(
            {
                "group_member_count": len(final_members),
                "identity_exact": identity_exact,
                "phase": "descendant_emptiness",
                "sent": False,
                "signal": None,
            }
        )
        payload: dict[str, object] = {
            "cleanup_call_counts": {
                "agent_turn": 0,
                "approval_resolution": 0,
                "evidence_collector": 0,
                "provider": 0,
                "runner": 0,
                "scientific_retry": 0,
            },
            "cutover_eligible": semantics.cutover_eligible,
            "descendant_residue_observed": descendant_residue_observed,
            "exact_charge_claimed": False,
            "external_outcome": semantics.external_outcome,
            "identity": self.identity.to_dict(),
            "identity_exact": identity_exact,
            "mode": self.mode,
            "normal_bundle_created": False,
            "operator_signal": (
                None if operator_signal is None else int(operator_signal)
            ),
            "outcome": "fatal",
            "phases": phases,
            "quarantine_required": semantics.quarantine_required,
            "quiescence_claimed": False,
            "raw_exit_code": raw_exit_code,
            "raw_signal": semantics.raw_signal,
            "ready_frame_digest": self.ready_frame_digest,
            "remote_cancellation_claimed": False,
            "retirement_proven": semantics.retirement_proven,
            "schema_id": FAULT_EVIDENCE_SCHEMA_ID,
        }
        self._evidence = FaultProcessEvidence(
            payload=payload,
            evidence_digest=_digest(payload),
        )
        return self._evidence


@dataclass(frozen=True, slots=True)
class IdentityBoundFaultProcessRunner:
    registry: Mapping[str, object]
    ledger: ExternalEffectLedger
    safety_guard: QualificationSafetyGuard
    readiness_timeout_seconds: float = 10.0
    operator_grace_seconds: float = 2.0
    term_grace_seconds: float = 2.0
    kill_grace_seconds: float = 5.0
    deadline_seconds: float = 2.0

    def start(
        self,
        mode: str,
        *,
        scenario_root: Path | None = None,
    ) -> IdentityBoundFaultProcessHandle:
        if mode not in FAULT_CHILD_MODES:
            raise ValueError(f"unsupported fault child mode {mode!r}")
        if mode == "host_dispatch_in_doubt" and scenario_root is None:
            raise ValueError("Host fault child requires a scenario root")
        read_descriptor, write_descriptor = os.pipe()
        process: subprocess.Popen[bytes] | None = None
        launch_nonce = secrets.token_hex(32)
        environment = scrubbed_environment()
        environment[_CONTROL_FD_ENV] = str(write_descriptor)
        environment[_LAUNCH_NONCE_ENV] = launch_nonce
        if scenario_root is not None:
            environment[_SCENARIO_ROOT_ENV] = str(scenario_root.absolute())
        tests_root = Path(__file__).resolve().parents[1]
        argv = (
            sys.executable,
            "-m",
            "architecture_qualification.fault_process_child",
            "--mode",
            mode,
        )
        try:
            process = self.safety_guard.launch_local_fault_process(
                ledger=self.ledger,
                port_id=FAULT_PROCESS_PORT_ID,
                argv=argv,
                cwd=tests_root,
                environment=environment,
                pass_fds=(write_descriptor,),
            )
            os.close(write_descriptor)
            write_descriptor = -1
            content = _read_ready_frame(
                read_descriptor,
                process=process,
                timeout_seconds=self.readiness_timeout_seconds,
            )
            identity, payload, frame_digest = _validate_ready_frame(
                content,
                process=process,
                mode=mode,
                launch_nonce=launch_nonce,
            )
            return IdentityBoundFaultProcessHandle(
                process=process,
                identity=identity,
                mode=mode,
                ready_payload=payload,
                ready_frame_digest=frame_digest,
                operator_grace_seconds=self.operator_grace_seconds,
                term_grace_seconds=self.term_grace_seconds,
                kill_grace_seconds=self.kill_grace_seconds,
                deadline_seconds=self.deadline_seconds,
            )
        except BaseException:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=self.term_grace_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.kill_grace_seconds)
            if process is not None and process.stderr is not None:
                process.stderr.close()
            raise
        finally:
            os.close(read_descriptor)
            if write_descriptor >= 0:
                os.close(write_descriptor)


__all__ = [
    "FAULT_CHILD_MODES",
    "FAULT_EVIDENCE_SCHEMA_ID",
    "FAULT_PROCESS_PORT_ID",
    "FAULT_READY_SCHEMA_ID",
    "FaultProcessEvidence",
    "FaultProcessIdentity",
    "FaultProcessProtocolError",
    "IdentityBoundFaultProcessHandle",
    "IdentityBoundFaultProcessRunner",
    "RetirementSemantics",
    "build_fault_ready_frame",
    "evaluate_retirement_semantics",
]
