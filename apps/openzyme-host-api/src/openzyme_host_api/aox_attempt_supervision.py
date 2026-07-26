from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
import pickle
import re
import secrets
import signal
import sqlite3
import stat
import time
from typing import Any
from uuid import uuid4

from openzyme_core import MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID
from openzyme_core import MutationLocalSettlementError
from openzyme_core import project_mutation_local_settlement

from .aox_cutover_evidence import AttemptRunContext
from .aox_cutover_evidence import AttemptRunner
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_cutover_evidence import safe_micu_ledger_snapshot


SUPERVISION_SCHEMA_ID_V1 = "aox_live_attempt_supervision@1"
SUPERVISION_SCHEMA_ID_V2 = "aox_live_attempt_supervision@2"
SUPERVISION_SCHEMA_ID = "aox_live_attempt_supervision@3"
SUPERVISION_RECEIPT_SCHEMA_ID_V1 = "aox_live_attempt_supervision_receipt@1"
SUPERVISION_RECEIPT_SCHEMA_ID_V2 = "aox_live_attempt_supervision_receipt@2"
SUPERVISION_RECEIPT_SCHEMA_ID = "aox_live_attempt_supervision_receipt@3"
SUPERVISION_FATAL_SCHEMA_ID_V1 = "aox_live_attempt_fatal@1"
SUPERVISION_FATAL_SCHEMA_ID = "aox_live_attempt_fatal@2"
SUPERVISION_RESULT_SCHEMA_ID = "aox_live_attempt_child_result@1"
MAX_FRAME_BYTES = 64 * 1024
RESULT_BASENAME = ".attempt-supervision-result.json"
DEFAULT_TERM_GRACE_SECONDS = 15.0
DEFAULT_KILL_GRACE_SECONDS = 10.0
_LEGACY_FRAME_TYPES = (
    "child_started",
    "quiescing",
    "quiescent",
    "child_terminal",
)
_FRAME_TYPES = (
    "child_started",
    "settling_local_state",
    "local_state_settled",
    "child_terminal",
)
_FRAME_KEYS = frozenset(
    {
        "schema_id",
        "campaign_id",
        "attempt_id",
        "attempt_kind",
        "attempt_authority_id",
        "attempt_authority_request_digest",
        "parent_process_nonce",
        "child_process_nonce",
        "process_epoch",
        "sequence",
        "emitted_at_monotonic_ns",
        "frame_type",
        "payload",
        "payload_digest",
        "previous_frame_digest",
        "frame_digest",
    }
)
_PAYLOAD_KEYS = {
    "child_started": frozenset(
        {"child_pid", "child_pgid", "child_start_time_ticks", "root_identity"}
    ),
    "settling_local_state": frozenset({"result_pending"}),
    "local_state_settled": frozenset(
        {
            "mutation_authority_schema_id",
            "mutation_authority_snapshot_digest",
            "mutation_authority_observed_row_count",
            "nonterminal_mutation_scope_count",
            "active_mutation_writer_count",
            "sqlite_checkpoint",
            "sqlite_integrity",
            "declared_root_sync",
            "result_digest",
        }
    ),
    "child_terminal": frozenset(
        {"outcome", "failure_code", "failure_type", "result_digest"}
    ),
}
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_NONCE_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_EPOCH_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_FAILURE_TYPE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


SUPERVISOR_CONTRACT_BASE = {
    "schema_id": SUPERVISION_SCHEMA_ID,
    "frame_types": list(_FRAME_TYPES),
    "serialization": "canonical_json_utf8",
    "frame_limit_bytes": MAX_FRAME_BYTES,
    "digest": "sha256",
    "start_method": "spawn",
    "session_boundary": "posix_setsid_process_group",
    "retirement_ladder": ["sigterm", "sigkill", "waitpid", "group_empty"],
    "normal_gate": [
        "local_state_settled",
        "child_terminal_normal",
        "zero_exit",
        "group_empty",
        "parent_snapshot_revalidated",
        "result_digest_match",
    ],
}
_LEGACY_SUPERVISOR_CONTRACT_BASE = {
    "schema_id": SUPERVISION_SCHEMA_ID_V2,
    "frame_types": list(_LEGACY_FRAME_TYPES),
    "serialization": "canonical_json_utf8",
    "frame_limit_bytes": MAX_FRAME_BYTES,
    "digest": "sha256",
    "start_method": "spawn",
    "session_boundary": "posix_setsid_process_group",
    "retirement_ladder": ["sigterm", "sigkill", "waitpid", "group_empty"],
    "normal_gate": [
        "quiescent",
        "child_terminal_normal",
        "zero_exit",
        "group_empty",
        "result_digest_match",
    ],
}


class AttemptSupervisionProtocolError(ValueError):
    pass


class AttemptRootAccessError(RuntimeError):
    pass


class AttemptLocalSettlementError(RuntimeError):
    retryable = False

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class AttemptSupervisionFatalError(RuntimeError):
    attempt_supervision_fatal = True

    def __init__(self, code: str, *, fatal_evidence_digest: str | None) -> None:
        self.code = code
        self.fatal_evidence_digest = fatal_evidence_digest
        super().__init__(f"{code}: process-isolated attempt supervision failed")


@dataclass(slots=True)
class AttemptRootAccessGate:
    attempt_root: Path
    process_epoch: str
    child_pid: int
    _retired: bool = False
    _attempted_access_count: int = 0

    @property
    def retired(self) -> bool:
        return self._retired

    @property
    def attempted_access_count(self) -> int:
        return self._attempted_access_count

    def retire(
        self,
        *,
        process_epoch: str,
        child_pid: int,
        descendant_retirement_proven: bool,
    ) -> None:
        if (
            process_epoch != self.process_epoch
            or child_pid != self.child_pid
            or descendant_retirement_proven is not True
        ):
            raise AttemptRootAccessError("attempt root retirement identity mismatch")
        self._retired = True

    def read_bytes(self, target: Path) -> bytes:
        if not self._retired:
            self._attempted_access_count += 1
            raise AttemptRootAccessError(
                "attempt roots remain unreadable until process retirement"
            )
        root = self.attempt_root.resolve(strict=True)
        resolved = target.resolve(strict=True)
        if target.is_symlink() or (resolved != root and root not in resolved.parents):
            raise AttemptRootAccessError("attempt root target identity mismatch")
        return target.read_bytes()


@dataclass(frozen=True, slots=True)
class _ProtocolIdentity:
    campaign_id: str
    attempt_id: str
    attempt_kind: str
    attempt_authority_id: str
    attempt_authority_request_digest: str
    parent_process_nonce: str
    process_epoch: str
    root_identity: str


@dataclass(slots=True)
class LifecycleFrameValidator:
    identity: _ProtocolIdentity
    child_process_nonce: str | None = None
    last_sequence: int = 0
    last_digest: str | None = None
    frame_types: list[str] = field(default_factory=list)
    settlement_payload: dict[str, object] | None = None
    terminal_payload: dict[str, object] | None = None

    def accept(self, content: bytes) -> dict[str, object]:
        if len(content) > MAX_FRAME_BYTES:
            raise AttemptSupervisionProtocolError("lifecycle frame is oversized")
        frame = _strict_canonical_object(content)
        if set(frame) != _FRAME_KEYS:
            raise AttemptSupervisionProtocolError("lifecycle frame fields are not closed")
        if frame.get("schema_id") != SUPERVISION_SCHEMA_ID:
            raise AttemptSupervisionProtocolError("lifecycle schema is unsupported")
        expected_identity = {
            "campaign_id": self.identity.campaign_id,
            "attempt_id": self.identity.attempt_id,
            "attempt_kind": self.identity.attempt_kind,
            "attempt_authority_id": self.identity.attempt_authority_id,
            "attempt_authority_request_digest": (
                self.identity.attempt_authority_request_digest
            ),
            "parent_process_nonce": self.identity.parent_process_nonce,
            "process_epoch": self.identity.process_epoch,
        }
        if any(frame.get(key) != value for key, value in expected_identity.items()):
            raise AttemptSupervisionProtocolError("lifecycle identity drifted")
        child_nonce = frame.get("child_process_nonce")
        if not isinstance(child_nonce, str) or _NONCE_PATTERN.fullmatch(child_nonce) is None:
            raise AttemptSupervisionProtocolError("child nonce is invalid")
        if self.child_process_nonce is None:
            self.child_process_nonce = child_nonce
        elif self.child_process_nonce != child_nonce:
            raise AttemptSupervisionProtocolError("child nonce drifted")
        sequence = frame.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise AttemptSupervisionProtocolError("frame sequence is invalid")
        if sequence != self.last_sequence + 1:
            raise AttemptSupervisionProtocolError("frame sequence is not contiguous")
        emitted = frame.get("emitted_at_monotonic_ns")
        if not isinstance(emitted, int) or isinstance(emitted, bool) or emitted <= 0:
            raise AttemptSupervisionProtocolError("frame monotonic time is invalid")
        frame_type = frame.get("frame_type")
        if frame_type not in _FRAME_TYPES:
            raise AttemptSupervisionProtocolError("frame type is unsupported")
        if self.terminal_payload is not None:
            raise AttemptSupervisionProtocolError("frame followed terminal state")
        if not self.frame_types and frame_type != "child_started":
            raise AttemptSupervisionProtocolError("first frame is not child_started")
        if frame_type in self.frame_types:
            raise AttemptSupervisionProtocolError("frame type was duplicated")
        if frame_type == "settling_local_state" and self.frame_types != [
            "child_started"
        ]:
            raise AttemptSupervisionProtocolError(
                "local settlement start frame is out of order"
            )
        if frame_type == "local_state_settled" and self.frame_types != [
            "child_started",
            "settling_local_state",
        ]:
            raise AttemptSupervisionProtocolError(
                "local settlement frame is out of order"
            )
        payload = frame.get("payload")
        if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS[frame_type]:
            raise AttemptSupervisionProtocolError("frame payload fields are not closed")
        _validate_frame_payload(frame_type, payload, identity=self.identity)
        payload_digest = frame.get("payload_digest")
        if payload_digest != canonical_digest(payload):
            raise AttemptSupervisionProtocolError("frame payload digest mismatch")
        if frame.get("previous_frame_digest") != self.last_digest:
            raise AttemptSupervisionProtocolError("frame hash chain is invalid")
        declared_digest = frame.get("frame_digest")
        material = {key: value for key, value in frame.items() if key != "frame_digest"}
        if declared_digest != canonical_digest(material):
            raise AttemptSupervisionProtocolError("frame digest mismatch")
        self.last_sequence = sequence
        self.last_digest = str(declared_digest)
        self.frame_types.append(str(frame_type))
        if frame_type == "local_state_settled":
            self.settlement_payload = dict(payload)
        elif frame_type == "child_terminal":
            self.terminal_payload = dict(payload)
        return frame


def _strict_canonical_object(content: bytes) -> dict[str, object]:
    try:
        text = content.decode("utf-8")

        def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result

        payload = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AttemptSupervisionProtocolError("lifecycle frame is not strict JSON") from exc
    if not isinstance(payload, dict) or canonical_json_bytes(payload) != content:
        raise AttemptSupervisionProtocolError("lifecycle frame is not canonical JSON")
    return dict(payload)


def _validate_frame_payload(
    frame_type: str,
    payload: Mapping[str, object],
    *,
    identity: _ProtocolIdentity,
) -> None:
    if frame_type == "child_started":
        integers = ("child_pid", "child_pgid", "child_start_time_ticks")
        if any(
            not isinstance(payload.get(key), int)
            or isinstance(payload.get(key), bool)
            or int(payload[key]) <= 0
            for key in integers
        ) or payload.get("root_identity") != identity.root_identity:
            raise AttemptSupervisionProtocolError("child start identity is invalid")
        return
    if frame_type == "settling_local_state":
        if payload.get("result_pending") is not True:
            raise AttemptSupervisionProtocolError(
                "local settlement start payload is invalid"
            )
        return
    if frame_type == "local_state_settled":
        if (
            payload.get("mutation_authority_schema_id")
            != MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID
            or _DIGEST_PATTERN.fullmatch(
                str(payload.get("mutation_authority_snapshot_digest") or "")
            )
            is None
            or not _is_nonnegative_int(
                payload.get("mutation_authority_observed_row_count")
            )
            or not _is_nonnegative_int(
                payload.get("nonterminal_mutation_scope_count")
            )
            or payload.get("active_mutation_writer_count") != 0
            or payload.get("sqlite_checkpoint") not in {"passed", "not_present"}
            or payload.get("sqlite_integrity") not in {"passed", "not_present"}
            or payload.get("declared_root_sync") is not True
            or _DIGEST_PATTERN.fullmatch(str(payload.get("result_digest") or ""))
            is None
        ):
            raise AttemptSupervisionProtocolError(
                "local settlement payload is invalid"
            )
        return
    outcome = payload.get("outcome")
    result_digest = payload.get("result_digest")
    if outcome == "normal":
        if (
            payload.get("failure_code") is not None
            or payload.get("failure_type") is not None
            or _DIGEST_PATTERN.fullmatch(str(result_digest or "")) is None
        ):
            raise AttemptSupervisionProtocolError("normal terminal payload is invalid")
    elif outcome == "fatal":
        if (
            not isinstance(payload.get("failure_code"), str)
            or _ERROR_CODE_PATTERN.fullmatch(str(payload["failure_code"])) is None
            or not isinstance(payload.get("failure_type"), str)
            or _FAILURE_TYPE_PATTERN.fullmatch(str(payload["failure_type"]))
            is None
            or result_digest is not None
        ):
            raise AttemptSupervisionProtocolError("fatal terminal payload is invalid")
    else:
        raise AttemptSupervisionProtocolError("terminal outcome is invalid")


def build_lifecycle_frame(
    *,
    identity: _ProtocolIdentity,
    child_process_nonce: str,
    sequence: int,
    frame_type: str,
    payload: Mapping[str, object],
    previous_frame_digest: str | None,
) -> tuple[bytes, str]:
    material: dict[str, object] = {
        "schema_id": SUPERVISION_SCHEMA_ID,
        "campaign_id": identity.campaign_id,
        "attempt_id": identity.attempt_id,
        "attempt_kind": identity.attempt_kind,
        "attempt_authority_id": identity.attempt_authority_id,
        "attempt_authority_request_digest": (
            identity.attempt_authority_request_digest
        ),
        "parent_process_nonce": identity.parent_process_nonce,
        "child_process_nonce": child_process_nonce,
        "process_epoch": identity.process_epoch,
        "sequence": sequence,
        "emitted_at_monotonic_ns": time.monotonic_ns(),
        "frame_type": frame_type,
        "payload": dict(payload),
        "payload_digest": canonical_digest(dict(payload)),
        "previous_frame_digest": previous_frame_digest,
    }
    digest = canonical_digest(material)
    content = canonical_json_bytes({**material, "frame_digest": digest})
    if len(content) > MAX_FRAME_BYTES:
        raise AttemptSupervisionProtocolError("lifecycle frame is oversized")
    return content, digest


@dataclass(slots=True)
class _ChildEmitter:
    connection: Connection
    identity: _ProtocolIdentity
    child_process_nonce: str
    sequence: int = 0
    previous_digest: str | None = None

    def emit(self, frame_type: str, payload: Mapping[str, object]) -> None:
        self.sequence += 1
        content, digest = build_lifecycle_frame(
            identity=self.identity,
            child_process_nonce=self.child_process_nonce,
            sequence=self.sequence,
            frame_type=frame_type,
            payload=payload,
            previous_frame_digest=self.previous_digest,
        )
        self.connection.send_bytes(content)
        self.previous_digest = digest


def _process_start_time_ticks(pid: int) -> int:
    content = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    close = content.rfind(")")
    if close < 0:
        raise ValueError("process stat comm terminator missing")
    fields = content[close + 2 :].split()
    if len(fields) < 20:
        raise ValueError("process stat is truncated")
    return int(fields[19])


def _process_group_members(pgid: int) -> tuple[int, ...]:
    members: list[int] = []
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            content = (entry / "stat").read_text(encoding="utf-8")
            close = content.rfind(")")
            fields = content[close + 2 :].split()
            process_group = int(fields[2])
            state = fields[0]
        except (OSError, ValueError, IndexError):
            continue
        if process_group == pgid and state != "Z":
            members.append(int(entry.name))
    return tuple(sorted(members))


def _stable_failure_code(exc: BaseException) -> str:
    candidate = getattr(exc, "code", None)
    if isinstance(candidate, str) and _ERROR_CODE_PATTERN.fullmatch(candidate):
        return candidate
    return "attempt_child_runner_failed"


def _safe_failure_type(value: object) -> str:
    candidate = str(value or "")
    if _FAILURE_TYPE_PATTERN.fullmatch(candidate) is not None:
        return candidate
    return "AttemptSupervisionFailure"


def _write_exclusive_bytes(path: Path, content: bytes, *, final_mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
        os.fsync(descriptor)
        os.fchmod(descriptor, final_mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _empty_mutation_settlement() -> dict[str, object]:
    connection = sqlite3.connect(":memory:")
    try:
        return project_mutation_local_settlement(connection).to_dict()
    finally:
        connection.close()


def _sqlite_local_settlement(
    path: Path,
    *,
    read_only: bool = False,
) -> dict[str, object]:
    if not path.is_file():
        return {
            "sqlite_checkpoint": "not_present",
            "sqlite_integrity": "not_present",
            **_empty_mutation_settlement(),
        }
    connection = (
        sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=5.0,
        )
        if read_only
        else sqlite3.connect(path, timeout=5.0)
    )
    try:
        connection.execute("PRAGMA busy_timeout = 5000")
        if read_only:
            connection.execute("PRAGMA query_only = ON")
            checkpoint_status = "parent_read_only"
        else:
            try:
                checkpoint = connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
            except sqlite3.DatabaseError as exc:
                raise AttemptLocalSettlementError(
                    "attempt_sqlite_checkpoint_failed",
                    "SQLite WAL checkpoint failed",
                ) from exc
            if checkpoint is None or int(checkpoint[0]) != 0:
                raise AttemptLocalSettlementError(
                    "attempt_sqlite_checkpoint_busy",
                    "SQLite WAL checkpoint remained busy",
                )
            checkpoint_status = "passed"
        try:
            integrity = [
                str(row[0]) for row in connection.execute("PRAGMA integrity_check")
            ]
        except sqlite3.DatabaseError as exc:
            raise AttemptLocalSettlementError(
                "attempt_sqlite_integrity_failed",
                "SQLite integrity check failed",
            ) from exc
        if integrity != ["ok"]:
            raise AttemptLocalSettlementError(
                "attempt_sqlite_integrity_failed",
                "SQLite integrity check did not close",
            )
        try:
            projection = project_mutation_local_settlement(connection)
        except MutationLocalSettlementError as exc:
            code = (
                "attempt_mutation_writers_active"
                if exc.code == "mutation_writers_active"
                else "attempt_mutation_snapshot_invalid"
            )
            raise AttemptLocalSettlementError(
                code,
                "mutation authority local settlement failed",
            ) from exc
        return {
            "sqlite_checkpoint": checkpoint_status,
            "sqlite_integrity": "passed",
            **projection.to_dict(),
        }
    finally:
        connection.close()


def _fsync_tree(path: Path) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise RuntimeError("declared attempt root contains a symbolic link")
    if stat.S_ISREG(metadata.st_mode):
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return
    if not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("declared attempt root contains an unsupported entry")
    for child in sorted(path.iterdir(), key=lambda item: item.name):
        _fsync_tree(child)
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _child_result_payload(
    *,
    context: AttemptRunContext,
    identity: _ProtocolIdentity,
    evidence: Mapping[str, object],
) -> dict[str, object]:
    normalized_evidence = dict(evidence)
    return {
        "schema_id": SUPERVISION_RESULT_SCHEMA_ID,
        "campaign_id": identity.campaign_id,
        "attempt_id": identity.attempt_id,
        "attempt_kind": identity.attempt_kind,
        "attempt_authority_id": identity.attempt_authority_id,
        "attempt_authority_request_digest": (
            identity.attempt_authority_request_digest
        ),
        "process_epoch": identity.process_epoch,
        "root_identity": str(context.roots.proof.get("root_identity") or ""),
        "evidence": normalized_evidence,
        "evidence_digest": canonical_digest(normalized_evidence),
    }


def _attempt_child_main(
    runner: AttemptRunner,
    context: AttemptRunContext,
    connection: Connection,
    identity: _ProtocolIdentity,
) -> None:
    emitter: _ChildEmitter | None = None
    try:
        os.setsid()
        child_pid = os.getpid()
        child_pgid = os.getpgrp()
        if child_pgid != child_pid:
            raise RuntimeError("child did not acquire a dedicated process group")
        emitter = _ChildEmitter(
            connection=connection,
            identity=identity,
            child_process_nonce=secrets.token_hex(32),
        )
        emitter.emit(
            "child_started",
            {
                "child_pid": child_pid,
                "child_pgid": child_pgid,
                "child_start_time_ticks": _process_start_time_ticks(child_pid),
                "root_identity": identity.root_identity,
            },
        )
        evidence = runner(context)
        if not isinstance(evidence, Mapping):
            raise TypeError("attempt runner result must be a mapping")
        emitter.emit("settling_local_state", {"result_pending": True})
        result_payload = _child_result_payload(
            context=context,
            identity=identity,
            evidence=evidence,
        )
        result_content = canonical_json_bytes(result_payload)
        result_digest = canonical_digest(result_payload)
        _write_exclusive_bytes(
            context.roots.evidence_root / RESULT_BASENAME,
            result_content,
            final_mode=0o400,
        )
        settlement = _sqlite_local_settlement(context.roots.sqlite_path)
        try:
            _fsync_tree(context.roots.attempt_root)
        except (OSError, RuntimeError) as exc:
            raise AttemptLocalSettlementError(
                "attempt_root_sync_failed",
                "declared attempt root synchronization failed",
            ) from exc
        settlement_payload = {
            "mutation_authority_schema_id": settlement["schema_id"],
            "mutation_authority_snapshot_digest": settlement["snapshot_digest"],
            "mutation_authority_observed_row_count": settlement[
                "observed_row_count"
            ],
            "nonterminal_mutation_scope_count": settlement[
                "nonterminal_scope_count"
            ],
            "active_mutation_writer_count": settlement["active_writer_count"],
            "sqlite_checkpoint": settlement["sqlite_checkpoint"],
            "sqlite_integrity": settlement["sqlite_integrity"],
            "declared_root_sync": True,
            "result_digest": result_digest,
        }
        emitter.emit("local_state_settled", settlement_payload)
        emitter.emit(
            "child_terminal",
            {
                "outcome": "normal",
                "failure_code": None,
                "failure_type": None,
                "result_digest": result_digest,
            },
        )
    except BaseException as exc:
        if emitter is not None:
            try:
                emitter.emit(
                    "child_terminal",
                    {
                        "outcome": "fatal",
                        "failure_code": _stable_failure_code(exc),
                        "failure_type": _safe_failure_type(type(exc).__name__),
                        "result_digest": None,
                    },
                )
            except BaseException:
                pass
        raise SystemExit(70) from None
    finally:
        connection.close()


def derive_live_attempt_supervision_timeout_seconds(
    *,
    attempt_timeout_seconds: float,
    browser_approval_timeout_seconds: float,
    browser_completion_hold_seconds: float,
    browser_observation_submission_timeout_seconds: float,
) -> float:
    values = (
        attempt_timeout_seconds,
        browser_approval_timeout_seconds,
        browser_completion_hold_seconds,
        browser_observation_submission_timeout_seconds,
    )
    if (
        any(not math.isfinite(value) or value < 0 for value in values)
        or attempt_timeout_seconds <= 0
    ):
        raise ValueError("live supervision bounds must be non-negative")
    return (
        2.0 * attempt_timeout_seconds
        + browser_approval_timeout_seconds
        + browser_completion_hold_seconds
        + browser_observation_submission_timeout_seconds
        + 120.0
    )


def _retire_process_group(
    process: multiprocessing.Process,
    *,
    pgid: int | None,
    child_start_time_ticks: int | None,
    term_grace_seconds: float,
    kill_grace_seconds: float,
) -> tuple[bool, list[dict[str, object]]]:
    phases: list[dict[str, object]] = []

    def members() -> tuple[int, ...]:
        return () if pgid is None else _process_group_members(pgid)

    exact_group_identity = pgid is not None and pgid == process.pid
    if exact_group_identity and child_start_time_ticks is not None:
        try:
            current_start = _process_start_time_ticks(pgid)
        except (OSError, ValueError):
            current_start = None
        if current_start is not None and current_start != child_start_time_ticks:
            exact_group_identity = False
    if not exact_group_identity:
        if process.is_alive():
            process.terminate()
            process.join(timeout=term_grace_seconds)
            if process.is_alive():
                process.kill()
                process.join(timeout=kill_grace_seconds)
        phases.append(
            {
                "phase": "identity_check",
                "sent": False,
                "observed_at_monotonic_ns": time.monotonic_ns(),
                "group_member_count": 0,
            }
        )
        return False, phases

    before = members()
    term_sent = False
    try:
        if pgid is not None and before:
            os.killpg(pgid, signal.SIGTERM)
            term_sent = True
        elif process.is_alive():
            process.terminate()
            term_sent = True
    except ProcessLookupError:
        pass
    phases.append(
        {
            "phase": "sigterm",
            "sent": term_sent,
            "observed_at_monotonic_ns": time.monotonic_ns(),
            "group_member_count": len(before),
        }
    )
    term_deadline = time.monotonic() + term_grace_seconds
    while time.monotonic() < term_deadline:
        process.join(timeout=min(0.05, max(0.0, term_deadline - time.monotonic())))
        if not process.is_alive() and not members():
            break
    remaining = members()
    kill_sent = False
    try:
        if pgid is not None and remaining:
            os.killpg(pgid, signal.SIGKILL)
            kill_sent = True
        elif process.is_alive():
            process.kill()
            kill_sent = True
    except ProcessLookupError:
        pass
    phases.append(
        {
            "phase": "sigkill",
            "sent": kill_sent,
            "observed_at_monotonic_ns": time.monotonic_ns(),
            "group_member_count": len(remaining),
        }
    )
    kill_deadline = time.monotonic() + kill_grace_seconds
    while time.monotonic() < kill_deadline:
        process.join(timeout=min(0.05, max(0.0, kill_deadline - time.monotonic())))
        if not process.is_alive() and not members():
            break
    process.join(timeout=0)
    final_members = members()
    proven = pgid is not None and process.exitcode is not None and not final_members
    phases.append(
        {
            "phase": "retirement_check",
            "sent": False,
            "observed_at_monotonic_ns": time.monotonic_ns(),
            "group_member_count": len(final_members),
        }
    )
    return proven, phases


def _write_fatal_evidence(
    *,
    context: AttemptRunContext,
    ledger_path: Path,
    identity: _ProtocolIdentity,
    validator: LifecycleFrameValidator,
    failure_code: str,
    failure_type: str,
    child_pid: int | None,
    child_pgid: int | None,
    child_start_time_ticks: int | None,
    deadline_seconds: float,
    child_exit_code: int | None,
    descendant_retirement_proven: bool,
    termination_ladder: list[dict[str, object]],
    root_gate: AttemptRootAccessGate | None,
) -> str:
    ledger_summary: dict[str, object] | None = None
    if descendant_retirement_proven:
        try:
            ledger_summary = safe_micu_ledger_snapshot(ledger_path)
        except Exception:
            ledger_summary = None
    payload: dict[str, object] = {
        "schema_id": SUPERVISION_FATAL_SCHEMA_ID,
        "campaign_id": identity.campaign_id,
        "attempt_id": identity.attempt_id,
        "attempt_kind": identity.attempt_kind,
        "attempt_authority_id": identity.attempt_authority_id,
        "attempt_authority_request_digest": (
            identity.attempt_authority_request_digest
        ),
        "process_epoch": identity.process_epoch,
        "parent_process_nonce_digest": canonical_digest(
            {"nonce": identity.parent_process_nonce}
        ),
        "child_process_nonce_digest": (
            None
            if validator.child_process_nonce is None
            else canonical_digest({"nonce": validator.child_process_nonce})
        ),
        "child_pid": child_pid,
        "child_pgid": child_pgid,
        "child_start_time_ticks": child_start_time_ticks,
        "deadline_seconds": deadline_seconds,
        "failure_code": failure_code,
        "failure_type": _safe_failure_type(failure_type),
        "termination_ladder": termination_ladder,
        "child_exit_code": child_exit_code,
        "child_signal": (
            -child_exit_code
            if isinstance(child_exit_code, int) and child_exit_code < 0
            else None
        ),
        "last_valid_sequence": validator.last_sequence,
        "last_valid_frame_digest": validator.last_digest,
        "local_settlement_observed": validator.settlement_payload is not None,
        "descendant_retirement_proven": descendant_retirement_proven,
        "root_access_rejection_count": (
            0 if root_gate is None else root_gate.attempted_access_count
        ),
        "micu_verified_lower_bound": ledger_summary,
        "external_outcome": "unknown",
        "next_attempt_blocked": True,
        "cutover_eligible": False,
        "ledger_after_claimed": False,
        "sqlite_closure_claimed": False,
        "artifact_completeness_claimed": False,
    }
    fatal_digest = canonical_digest(payload)
    envelope = {"payload": payload, "fatal_digest": fatal_digest}
    failures_root = context.roots.attempt_root.parent / "failures"
    failures_root.mkdir(mode=0o700, exist_ok=True)
    if failures_root.is_symlink() or not failures_root.is_dir():
        raise RuntimeError("campaign failure root is invalid")
    target = failures_root / f"{context.roots.attempt_id}.fatal.json"
    _write_exclusive_bytes(
        target,
        canonical_json_bytes(envelope) + b"\n",
        final_mode=0o400,
    )
    return fatal_digest


def _validate_child_result(
    content: bytes,
    *,
    context: AttemptRunContext,
    identity: _ProtocolIdentity,
    expected_digest: str,
) -> dict[str, Any]:
    payload = _strict_canonical_object(content)
    expected_keys = {
        "schema_id",
        "campaign_id",
        "attempt_id",
        "attempt_kind",
        "attempt_authority_id",
        "attempt_authority_request_digest",
        "process_epoch",
        "root_identity",
        "evidence",
        "evidence_digest",
    }
    evidence = payload.get("evidence")
    if (
        set(payload) != expected_keys
        or canonical_digest(payload) != expected_digest
        or payload.get("schema_id") != SUPERVISION_RESULT_SCHEMA_ID
        or payload.get("campaign_id") != identity.campaign_id
        or payload.get("attempt_id") != identity.attempt_id
        or payload.get("attempt_kind") != identity.attempt_kind
        or payload.get("attempt_authority_id")
        != identity.attempt_authority_id
        or payload.get("attempt_authority_request_digest")
        != identity.attempt_authority_request_digest
        or payload.get("process_epoch") != identity.process_epoch
        or payload.get("root_identity")
        != str(context.roots.proof.get("root_identity") or "")
        or not isinstance(evidence, dict)
        or payload.get("evidence_digest") != canonical_digest(evidence)
    ):
        raise AttemptSupervisionProtocolError("child result binding is invalid")
    return dict(evidence)


def supervision_contract_digest(
    *,
    timeout_seconds: float,
    term_grace_seconds: float,
    kill_grace_seconds: float,
    protocol_schema_id: str = SUPERVISION_SCHEMA_ID,
) -> str:
    if protocol_schema_id == SUPERVISION_SCHEMA_ID:
        contract_base = SUPERVISOR_CONTRACT_BASE
    elif protocol_schema_id in {
        SUPERVISION_SCHEMA_ID_V1,
        SUPERVISION_SCHEMA_ID_V2,
    }:
        contract_base = _LEGACY_SUPERVISOR_CONTRACT_BASE
    else:
        raise ValueError("attempt supervision protocol schema is unsupported")
    return canonical_digest(
        {
            **contract_base,
            "schema_id": protocol_schema_id,
            "timeout_seconds": timeout_seconds,
            "term_grace_seconds": term_grace_seconds,
            "kill_grace_seconds": kill_grace_seconds,
        }
    )


def validate_attempt_supervision_receipt(
    receipt: object,
    *,
    attempt_id: str,
    attempt_kind: str,
    attempt_authority_id: str | None = None,
    attempt_authority_request_digest: str | None = None,
    expected_contract_digest: str | None = None,
    allow_legacy: bool = False,
) -> dict[str, object]:
    if not isinstance(receipt, Mapping):
        raise CutoverEvidenceError(
            "attempt_supervision_receipt_missing",
            "live cutover evidence requires process-isolated supervision",
            details={"identity": "product_path.attempt_supervision"},
        )
    normalized = dict(receipt)
    schema_id = normalized.get("schema_id")
    authority_expected = (
        attempt_authority_id is not None
        or attempt_authority_request_digest is not None
    )
    if authority_expected and (
        not isinstance(attempt_authority_id, str)
        or not attempt_authority_id
        or _DIGEST_PATTERN.fullmatch(
            str(attempt_authority_request_digest or "")
        )
        is None
    ):
        raise CutoverEvidenceError(
            "attempt_supervision_authority_invalid",
            "supervision validation requires one exact authority identity",
            details={"identity": "product_path.attempt_supervision"},
        )

    common_keys = {
        "schema_id",
        "mode",
        "attempt_id",
        "attempt_kind",
        "campaign_id",
        "process_epoch",
        "protocol_final_sequence",
        "protocol_final_digest",
        "child_exit_code",
        "descendant_retirement_proven",
        "sqlite_checkpoint",
        "sqlite_integrity",
        "declared_root_sync",
        "result_digest",
        "supervisor_contract_digest",
        "timeout_seconds",
        "term_grace_seconds",
        "kill_grace_seconds",
    }
    current_keys = common_keys | {
        "attempt_authority_id",
        "attempt_authority_request_digest",
        "local_state_settled",
        "parent_snapshot_revalidated",
        "mutation_authority_schema_id",
        "mutation_authority_snapshot_digest",
        "mutation_authority_observed_row_count",
        "nonterminal_mutation_scope_count",
        "active_mutation_writer_count",
    }
    legacy_keys = common_keys | {
        "quiescent",
        "active_mutation_scope_count",
        "active_mutation_writer_count",
    }
    base_digest_fields = (
        "campaign_id",
        "protocol_final_digest",
        "result_digest",
        "supervisor_contract_digest",
    )
    timeout_seconds = normalized.get("timeout_seconds")
    term_grace_seconds = normalized.get("term_grace_seconds")
    kill_grace_seconds = normalized.get("kill_grace_seconds")
    valid_bounds = (
        isinstance(timeout_seconds, (int, float))
        and not isinstance(timeout_seconds, bool)
        and math.isfinite(float(timeout_seconds))
        and float(timeout_seconds) > 0
        and isinstance(term_grace_seconds, (int, float))
        and not isinstance(term_grace_seconds, bool)
        and math.isfinite(float(term_grace_seconds))
        and float(term_grace_seconds) >= 0
        and isinstance(kill_grace_seconds, (int, float))
        and not isinstance(kill_grace_seconds, bool)
        and math.isfinite(float(kill_grace_seconds))
        and float(kill_grace_seconds) >= 0
    )
    common_valid = (
        normalized.get("mode") == "process_isolated_spawn"
        and normalized.get("attempt_id") == attempt_id
        and normalized.get("attempt_kind") == attempt_kind
        and _EPOCH_PATTERN.fullmatch(str(normalized.get("process_epoch") or ""))
        is not None
        and all(
            _DIGEST_PATTERN.fullmatch(str(normalized.get(key) or "")) is not None
            for key in base_digest_fields
        )
        and normalized.get("protocol_final_sequence") == 4
        and normalized.get("child_exit_code") == 0
        and normalized.get("descendant_retirement_proven") is True
        and normalized.get("sqlite_checkpoint") in {"passed", "not_present"}
        and normalized.get("sqlite_integrity") in {"passed", "not_present"}
        and normalized.get("declared_root_sync") is True
        and valid_bounds
    )

    if schema_id == SUPERVISION_RECEIPT_SCHEMA_ID:
        valid = (
            set(normalized) == current_keys
            and authority_expected
            and common_valid
            and normalized.get("attempt_authority_id") == attempt_authority_id
            and normalized.get("attempt_authority_request_digest")
            == attempt_authority_request_digest
            and _DIGEST_PATTERN.fullmatch(
                str(normalized.get("attempt_authority_request_digest") or "")
            )
            is not None
            and normalized.get("local_state_settled") is True
            and normalized.get("parent_snapshot_revalidated") is True
            and normalized.get("mutation_authority_schema_id")
            == MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID
            and _DIGEST_PATTERN.fullmatch(
                str(normalized.get("mutation_authority_snapshot_digest") or "")
            )
            is not None
            and _is_nonnegative_int(
                normalized.get("mutation_authority_observed_row_count")
            )
            and _is_nonnegative_int(
                normalized.get("nonterminal_mutation_scope_count")
            )
            and normalized.get("active_mutation_writer_count") == 0
        )
        protocol_schema_id = SUPERVISION_SCHEMA_ID
    elif schema_id in {
        SUPERVISION_RECEIPT_SCHEMA_ID_V1,
        SUPERVISION_RECEIPT_SCHEMA_ID_V2,
    }:
        legacy_authority = schema_id == SUPERVISION_RECEIPT_SCHEMA_ID_V2
        expected_keys = (
            legacy_keys
            | {"attempt_authority_id", "attempt_authority_request_digest"}
            if legacy_authority
            else legacy_keys
        )
        valid = (
            allow_legacy
            and set(normalized) == expected_keys
            and common_valid
            and authority_expected is legacy_authority
            and (
                not legacy_authority
                or (
                    normalized.get("attempt_authority_id")
                    == attempt_authority_id
                    and normalized.get("attempt_authority_request_digest")
                    == attempt_authority_request_digest
                    and _DIGEST_PATTERN.fullmatch(
                        str(
                            normalized.get(
                                "attempt_authority_request_digest"
                            )
                            or ""
                        )
                    )
                    is not None
                )
            )
            and normalized.get("quiescent") is True
            and normalized.get("active_mutation_scope_count") == 0
            and normalized.get("active_mutation_writer_count") == 0
        )
        protocol_schema_id = (
            SUPERVISION_SCHEMA_ID_V2
            if legacy_authority
            else SUPERVISION_SCHEMA_ID_V1
        )
    else:
        valid = False
        protocol_schema_id = SUPERVISION_SCHEMA_ID

    if (
        not valid
        or (
            valid_bounds
            and normalized.get("supervisor_contract_digest")
            != supervision_contract_digest(
                timeout_seconds=float(timeout_seconds),
                term_grace_seconds=float(term_grace_seconds),
                kill_grace_seconds=float(kill_grace_seconds),
                protocol_schema_id=protocol_schema_id,
            )
        )
        or (
            expected_contract_digest is not None
            and normalized.get("supervisor_contract_digest")
            != expected_contract_digest
        )
    ):
        raise CutoverEvidenceError(
            "attempt_supervision_receipt_invalid",
            "process supervision receipt does not prove exact local retirement",
            details={"identity": "product_path.attempt_supervision"},
        )
    return normalized


@dataclass(slots=True)
class ProcessIsolatedAttemptRunner:
    runner: AttemptRunner
    ledger_path: Path
    timeout_seconds: float
    term_grace_seconds: float = DEFAULT_TERM_GRACE_SECONDS
    kill_grace_seconds: float = DEFAULT_KILL_GRACE_SECONDS
    poll_interval_seconds: float = 0.05

    def __post_init__(self) -> None:
        if (
            os.name != "posix"
            or not Path("/proc/self/stat").is_file()
            or not hasattr(os, "setsid")
            or not hasattr(os, "killpg")
        ):
            raise ValueError("process-isolated live attempts require local POSIX /proc")
        if (
            not all(
                math.isfinite(value)
                for value in (
                    self.timeout_seconds,
                    self.term_grace_seconds,
                    self.kill_grace_seconds,
                    self.poll_interval_seconds,
                )
            )
            or self.timeout_seconds <= 0
            or self.term_grace_seconds < 0
            or self.kill_grace_seconds < 0
            or self.poll_interval_seconds <= 0
        ):
            raise ValueError("attempt supervision bounds are invalid")

    def __call__(self, context: AttemptRunContext) -> dict[str, Any]:
        authority = context.attempt_authority
        if (
            not isinstance(authority, dict)
            or not isinstance(authority.get("envelope_id"), str)
            or not isinstance(authority.get("request_digest"), str)
            or _DIGEST_PATTERN.fullmatch(str(authority["request_digest"]))
            is None
        ):
            raise AttemptSupervisionFatalError(
                "attempt_authority_missing",
                fatal_evidence_digest=None,
            )
        campaign_id = canonical_digest(
            {
                "identity": dict(context.identity),
                "campaign_root_identity": str(
                    context.roots.proof.get("allowed_prerequisite_digest") or ""
                ),
            }
        )
        identity = _ProtocolIdentity(
            campaign_id=campaign_id,
            attempt_id=context.roots.attempt_id,
            attempt_kind=context.roots.attempt_kind,
            attempt_authority_id=str(authority["envelope_id"]),
            attempt_authority_request_digest=str(
                authority["request_digest"]
            ),
            parent_process_nonce=secrets.token_hex(32),
            process_epoch=uuid4().hex,
            root_identity=str(context.roots.proof.get("root_identity") or ""),
        )
        validator = LifecycleFrameValidator(identity=identity)
        process: multiprocessing.Process | None = None
        parent_connection: Connection | None = None
        child_pgid: int | None = None
        child_start_time_ticks: int | None = None
        root_gate: AttemptRootAccessGate | None = None
        failure_code: str | None = None
        failure_type = "AttemptSupervisionFatal"
        termination_ladder: list[dict[str, object]] = []
        retirement_proven = False
        try:
            pickle.dumps((self.runner, context), protocol=pickle.HIGHEST_PROTOCOL)
            spawn = multiprocessing.get_context("spawn")
            parent_connection, child_connection = spawn.Pipe(duplex=False)
            process = spawn.Process(
                target=_attempt_child_main,
                args=(self.runner, context, child_connection, identity),
                name=f"aox-attempt-{context.roots.attempt_id}",
            )
            process.start()
            child_connection.close()
            if process.pid is None:
                raise RuntimeError("spawned attempt has no process id")
            root_gate = AttemptRootAccessGate(
                attempt_root=context.roots.attempt_root,
                process_epoch=identity.process_epoch,
                child_pid=process.pid,
            )
            deadline = time.monotonic() + self.timeout_seconds
            process_dead_at: float | None = None
            while True:
                now = time.monotonic()
                if now >= deadline:
                    failure_code = "attempt_child_timeout"
                    failure_type = "AttemptSupervisionTimeout"
                    break
                try:
                    available = parent_connection.poll(
                        min(self.poll_interval_seconds, deadline - now)
                    )
                except (OSError, EOFError):
                    available = False
                if available:
                    try:
                        content = parent_connection.recv_bytes(MAX_FRAME_BYTES)
                        frame = validator.accept(content)
                    except EOFError:
                        frame = None
                    except (OSError, AttemptSupervisionProtocolError):
                        failure_code = "attempt_supervision_protocol_invalid"
                        failure_type = "AttemptSupervisionProtocolError"
                        break
                    if frame is not None and frame["frame_type"] == "child_started":
                        payload = dict(frame["payload"])
                        child_pid = int(payload["child_pid"])
                        child_pgid = int(payload["child_pgid"])
                        child_start_time_ticks = int(payload["child_start_time_ticks"])
                        try:
                            observed_start = _process_start_time_ticks(process.pid)
                            observed_pgid = os.getpgid(process.pid)
                        except (OSError, ValueError):
                            observed_start = -1
                            observed_pgid = -1
                        if (
                            child_pid != process.pid
                            or child_pgid != process.pid
                            or child_start_time_ticks != observed_start
                            or child_pgid != observed_pgid
                        ):
                            failure_code = "attempt_child_identity_unproven"
                            failure_type = "AttemptProcessIdentityError"
                            break
                if not process.is_alive():
                    process.join(timeout=0)
                    process_dead_at = process_dead_at or time.monotonic()
                    if validator.terminal_payload is not None:
                        break
                    if time.monotonic() - process_dead_at >= max(
                        0.2, 2 * self.poll_interval_seconds
                    ):
                        failure_code = "attempt_local_settlement_missing"
                        failure_type = "AttemptProtocolTruncated"
                        break

            if failure_code is None and process is not None:
                process.join(timeout=0)
                if validator.terminal_payload is None:
                    failure_code = "attempt_local_settlement_missing"
                    failure_type = "AttemptProtocolTruncated"
                elif validator.terminal_payload.get("outcome") != "normal":
                    failure_code = str(
                        validator.terminal_payload.get("failure_code")
                        or "attempt_child_runner_failed"
                    )
                    failure_type = str(
                        validator.terminal_payload.get("failure_type")
                        or "AttemptChildFailure"
                    )
                elif process.exitcode != 0:
                    failure_code = "attempt_child_nonzero_exit"
                    failure_type = "AttemptChildExitError"
                elif validator.frame_types != list(_FRAME_TYPES):
                    failure_code = "attempt_local_settlement_missing"
                    failure_type = "AttemptProtocolTruncated"
                elif child_pgid is None or _process_group_members(child_pgid):
                    failure_code = "attempt_child_descendant_leak"
                    failure_type = "AttemptDescendantLeak"

            if failure_code is not None:
                if process is not None:
                    retirement_proven, termination_ladder = _retire_process_group(
                        process,
                        pgid=child_pgid,
                        child_start_time_ticks=child_start_time_ticks,
                        term_grace_seconds=self.term_grace_seconds,
                        kill_grace_seconds=self.kill_grace_seconds,
                    )
                if not retirement_proven:
                    failure_code = "attempt_child_descendant_retirement_unproven"
                fatal_digest = _write_fatal_evidence(
                    context=context,
                    ledger_path=self.ledger_path,
                    identity=identity,
                    validator=validator,
                    failure_code=failure_code,
                    failure_type=failure_type,
                    child_pid=None if process is None else process.pid,
                    child_pgid=child_pgid,
                    child_start_time_ticks=child_start_time_ticks,
                    deadline_seconds=self.timeout_seconds,
                    child_exit_code=None if process is None else process.exitcode,
                    descendant_retirement_proven=retirement_proven,
                    termination_ladder=termination_ladder,
                    root_gate=root_gate,
                )
                raise AttemptSupervisionFatalError(
                    failure_code,
                    fatal_evidence_digest=fatal_digest,
                )

            if process is None or process.pid is None or child_pgid is None:
                raise RuntimeError("attempt process identity disappeared")
            retirement_proven = (
                process.exitcode == 0 and not _process_group_members(child_pgid)
            )
            if not retirement_proven:
                failure_code = "attempt_child_descendant_retirement_unproven"
                retirement_proven, termination_ladder = _retire_process_group(
                    process,
                    pgid=child_pgid,
                    child_start_time_ticks=child_start_time_ticks,
                    term_grace_seconds=self.term_grace_seconds,
                    kill_grace_seconds=self.kill_grace_seconds,
                )
                fatal_digest = _write_fatal_evidence(
                    context=context,
                    ledger_path=self.ledger_path,
                    identity=identity,
                    validator=validator,
                    failure_code=failure_code,
                    failure_type="AttemptRetirementProofError",
                    child_pid=process.pid,
                    child_pgid=child_pgid,
                    child_start_time_ticks=child_start_time_ticks,
                    deadline_seconds=self.timeout_seconds,
                    child_exit_code=process.exitcode,
                    descendant_retirement_proven=retirement_proven,
                    termination_ladder=termination_ladder,
                    root_gate=root_gate,
                )
                raise AttemptSupervisionFatalError(
                    failure_code,
                    fatal_evidence_digest=fatal_digest,
                )
            if root_gate is None:
                raise RuntimeError("attempt root gate is missing")
            root_gate.retire(
                process_epoch=identity.process_epoch,
                child_pid=process.pid,
                descendant_retirement_proven=True,
            )
            settlement = validator.settlement_payload or {}
            terminal = validator.terminal_payload or {}
            expected_result_digest = str(terminal.get("result_digest") or "")
            if settlement.get("result_digest") != expected_result_digest:
                raise AttemptSupervisionProtocolError(
                    "terminal result digest differs from local settlement"
                )
            parent_settlement = _sqlite_local_settlement(
                context.roots.sqlite_path,
                read_only=True,
            )
            settlement_bindings = {
                "mutation_authority_schema_id": parent_settlement["schema_id"],
                "mutation_authority_snapshot_digest": parent_settlement[
                    "snapshot_digest"
                ],
                "mutation_authority_observed_row_count": parent_settlement[
                    "observed_row_count"
                ],
                "nonterminal_mutation_scope_count": parent_settlement[
                    "nonterminal_scope_count"
                ],
                "active_mutation_writer_count": parent_settlement[
                    "active_writer_count"
                ],
            }
            if (
                parent_settlement["active_writer_count"] != 0
                or any(
                    settlement.get(key) != value
                    for key, value in settlement_bindings.items()
                )
            ):
                raise AttemptLocalSettlementError(
                    "attempt_mutation_snapshot_drift",
                    "mutation authority changed after child local settlement",
                )
            result_content = root_gate.read_bytes(
                context.roots.evidence_root / RESULT_BASENAME
            )
            evidence = _validate_child_result(
                result_content,
                context=context,
                identity=identity,
                expected_digest=expected_result_digest,
            )
            product_path = dict(evidence.get("product_path") or {})
            if "attempt_supervision" in product_path:
                raise AttemptSupervisionProtocolError(
                    "child result tried to manufacture a supervision receipt"
                )
            receipt = {
                "schema_id": SUPERVISION_RECEIPT_SCHEMA_ID,
                "mode": "process_isolated_spawn",
                "attempt_id": identity.attempt_id,
                "attempt_kind": identity.attempt_kind,
                "attempt_authority_id": identity.attempt_authority_id,
                "attempt_authority_request_digest": (
                    identity.attempt_authority_request_digest
                ),
                "campaign_id": identity.campaign_id,
                "process_epoch": identity.process_epoch,
                "protocol_final_sequence": validator.last_sequence,
                "protocol_final_digest": validator.last_digest,
                "child_exit_code": process.exitcode,
                "local_state_settled": True,
                "descendant_retirement_proven": True,
                "parent_snapshot_revalidated": True,
                "mutation_authority_schema_id": settlement[
                    "mutation_authority_schema_id"
                ],
                "mutation_authority_snapshot_digest": settlement[
                    "mutation_authority_snapshot_digest"
                ],
                "mutation_authority_observed_row_count": settlement[
                    "mutation_authority_observed_row_count"
                ],
                "nonterminal_mutation_scope_count": settlement[
                    "nonterminal_mutation_scope_count"
                ],
                "active_mutation_writer_count": settlement[
                    "active_mutation_writer_count"
                ],
                "sqlite_checkpoint": settlement["sqlite_checkpoint"],
                "sqlite_integrity": settlement["sqlite_integrity"],
                "declared_root_sync": settlement["declared_root_sync"],
                "result_digest": expected_result_digest,
                "supervisor_contract_digest": supervision_contract_digest(
                    timeout_seconds=self.timeout_seconds,
                    term_grace_seconds=self.term_grace_seconds,
                    kill_grace_seconds=self.kill_grace_seconds,
                ),
                "timeout_seconds": self.timeout_seconds,
                "term_grace_seconds": self.term_grace_seconds,
                "kill_grace_seconds": self.kill_grace_seconds,
            }
            validate_attempt_supervision_receipt(
                receipt,
                attempt_id=identity.attempt_id,
                attempt_kind=identity.attempt_kind,
                attempt_authority_id=identity.attempt_authority_id,
                attempt_authority_request_digest=(
                    identity.attempt_authority_request_digest
                ),
            )
            product_path["attempt_supervision"] = receipt
            evidence["product_path"] = product_path
            return evidence
        except AttemptSupervisionFatalError:
            raise
        except Exception as exc:
            if process is None:
                retirement_proven = True
            else:
                retirement_proven, termination_ladder = _retire_process_group(
                    process,
                    pgid=child_pgid,
                    child_start_time_ticks=child_start_time_ticks,
                    term_grace_seconds=self.term_grace_seconds,
                    kill_grace_seconds=self.kill_grace_seconds,
                )
            if process is None:
                code = "attempt_child_spawn_unavailable"
            elif (
                retirement_proven
                and isinstance(getattr(exc, "code", None), str)
                and _ERROR_CODE_PATTERN.fullmatch(str(exc.code)) is not None
            ):
                code = str(exc.code)
            elif retirement_proven:
                code = "attempt_supervision_result_invalid"
            else:
                code = "attempt_child_descendant_retirement_unproven"
            fatal_digest = _write_fatal_evidence(
                context=context,
                ledger_path=self.ledger_path,
                identity=identity,
                validator=validator,
                failure_code=code,
                failure_type=type(exc).__name__,
                child_pid=None if process is None else process.pid,
                child_pgid=child_pgid,
                child_start_time_ticks=child_start_time_ticks,
                deadline_seconds=self.timeout_seconds,
                child_exit_code=None if process is None else process.exitcode,
                descendant_retirement_proven=retirement_proven,
                termination_ladder=termination_ladder,
                root_gate=root_gate,
            )
            raise AttemptSupervisionFatalError(
                code,
                fatal_evidence_digest=fatal_digest,
            ) from None
        finally:
            if parent_connection is not None:
                parent_connection.close()


__all__ = [
    "AttemptLocalSettlementError",
    "AttemptRootAccessError",
    "AttemptRootAccessGate",
    "AttemptSupervisionFatalError",
    "AttemptSupervisionProtocolError",
    "DEFAULT_KILL_GRACE_SECONDS",
    "DEFAULT_TERM_GRACE_SECONDS",
    "LifecycleFrameValidator",
    "MAX_FRAME_BYTES",
    "ProcessIsolatedAttemptRunner",
    "SUPERVISION_FATAL_SCHEMA_ID",
    "SUPERVISION_FATAL_SCHEMA_ID_V1",
    "SUPERVISION_RECEIPT_SCHEMA_ID",
    "SUPERVISION_RECEIPT_SCHEMA_ID_V1",
    "SUPERVISION_RECEIPT_SCHEMA_ID_V2",
    "SUPERVISION_SCHEMA_ID",
    "SUPERVISION_SCHEMA_ID_V1",
    "SUPERVISION_SCHEMA_ID_V2",
    "build_lifecycle_frame",
    "derive_live_attempt_supervision_timeout_seconds",
    "supervision_contract_digest",
    "validate_attempt_supervision_receipt",
]
