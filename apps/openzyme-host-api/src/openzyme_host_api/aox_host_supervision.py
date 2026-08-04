from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import threading
import time
from typing import Any, Iterator
from uuid import uuid4

import uvicorn

from openzyme_core import (
    MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID,
    MutationLocalSettlementError,
    SQLiteRepositoryProvider,
    project_mutation_local_settlement,
    sandbox_image_record,
)
from openzyme_core.sandbox_workspace import DEFAULT_SANDBOX_IMAGE_REF
from openzyme_domain import SandboxImageCompatibility
from openzyme_engines import PodmanPipelineSandboxRunner
from openzyme_engines.execution import validate_closed_sandbox_runtime_identity
from openzyme_runtime import OpenZymeSettings

from .aox_attempt_preflight import (
    ATTEMPT_PREFLIGHT_FILENAME,
    load_attempt_preflight_receipt,
)
from .aox_authority_storage import publish_private_canonical_authority
from .aox_cutover_evidence import (
    CutoverEvidenceError,
    canonical_digest,
    canonical_json_bytes,
)
from .aox_cutover_launch import build_aox_cutover_effective_config
from .aox_cutover_tool_policy import AoxFinalizationToolPrecondition
from .app import HostApiDependencies, create_app
from .foundation import build_configured_foundation


HOST_STARTUP_SCHEMA_ID = "aox_supervised_host_startup@4"
HOST_SUPERVISION_RECEIPT_SCHEMA_ID = "aox_supervised_host_receipt@3"
HOST_SUPERVISION_FATAL_SCHEMA_ID = "aox_supervised_host_fatal@1"
HOST_SANDBOX_BOOTSTRAP_SCHEMA_ID = "aox_supervised_host_sandbox_bootstrap@1"
SandboxBootstrapBinding = tuple[str, str, str]
_SANDBOX_BOOTSTRAP_FIELDS = {"schema_id", "preflight_receipt_digest", "runtime_identity", "registry_projection", "receipt_digest"}
HOST_STARTUP_FILENAME = "aox-host-startup.json"
HOST_SUPERVISION_FILENAME = "aox-host-supervision.json"
HOST_SUPERVISION_FATAL_FILENAME = "aox-host-supervision-fatal.json"
DEFAULT_STARTUP_TIMEOUT_SECONDS = 60.0
DEFAULT_TERM_GRACE_SECONDS = 15.0
DEFAULT_KILL_GRACE_SECONDS = 10.0
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_CONTRACT = {
    "schema_id": "aox_supervised_host_contract@1",
    "child_target": "configured_host_api", "network_boundary": "loopback_only",
    "runtime_policy": "public_commands_only", "automatic_runtime_drain": False,
    "automatic_approval": False, "automatic_rollover": False,
    "process_boundary": "spawn_posix_session",
    "retirement_ladder": ["cooperative", "sigterm", "sigkill", "group_empty"],
    "settlement": [
        "host_lifespan_retired", "mutation_writers_zero", "sqlite_checkpoint",
        "sqlite_integrity", "declared_roots_fsynced", "parent_snapshot_revalidated",
    ],
}
_RECEIPT_FIELDS = {
    "schema_id", "mode", "launch_id", "attempt_kind", "session_id",
    "root_ref", "authority_policy_digest",
    "campaign_id", "preflight_receipt_digest", "host_startup_receipt_digest",
    "process_epoch", "shutdown_reason", "child_exit_code", "local_state_settled",
    "descendant_retirement_proven", "parent_snapshot_revalidated",
    "mutation_authority_schema_id", "mutation_authority_snapshot_digest",
    "mutation_authority_observed_row_count", "nonterminal_mutation_scope_count",
    "active_mutation_writer_count", "sqlite_checkpoint", "sqlite_integrity",
    "declared_root_sync", "terminal_frame_digest", "timeout_seconds",
    "startup_timeout_seconds", "term_grace_seconds", "kill_grace_seconds",
    "supervisor_contract_digest", "retired_at", "receipt_digest",
}


class HostSupervisionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _validated_sandbox_runtime_identity(raw: object, binding: SandboxBootstrapBinding) -> dict[str, str]:
    _, image_digest, sdk_digest = binding
    try:
        return validate_closed_sandbox_runtime_identity(
            raw, configured_image_ref=DEFAULT_SANDBOX_IMAGE_REF, image_digest=image_digest,
            sdk_digest=sdk_digest, protocol_version="s10",
        )
    except ValueError as exc:
        code = str(exc) if str(exc) in {"missing", "invalid", "mismatch"} else "invalid"
        raise HostSupervisionError(f"host_sandbox_runtime_identity_{code}", "sandbox identity rejected") from exc


def supervised_host_sandbox_binding(preflight: Mapping[str, Any]) -> SandboxBootstrapBinding:
    prerequisites = dict(dict(preflight["root_proof"])["allowed_prerequisites"])
    return str(preflight["receipt_digest"]), str(prerequisites["image_digest"]), str(prerequisites["sdk_digest"])


def _sandbox_registry_projection(identity: Mapping[str, str]) -> dict[str, str]:
    return {"image_ref": DEFAULT_SANDBOX_IMAGE_REF.rsplit(":", 1)[0] + "@" + identity["image_digest"],
            "image_digest": identity["image_digest"], "sandbox_protocol_version": "s07",
            "manifest_schema_version": "s07.workspace_manifest.v1", "compatibility": SandboxImageCompatibility.COMPATIBLE.value}


def validate_supervised_host_sandbox_bootstrap(receipt: object, *, binding: SandboxBootstrapBinding) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise HostSupervisionError("host_sandbox_bootstrap_receipt_missing", "bootstrap receipt missing")
    value = dict(receipt)
    try:
        identity = _validated_sandbox_runtime_identity(value.get("runtime_identity"), binding)
    except HostSupervisionError as exc:
        raise HostSupervisionError("host_sandbox_bootstrap_receipt_invalid", "bootstrap identity invalid") from exc
    projection, preflight_receipt_digest = _sandbox_registry_projection(identity), binding[0]
    payload = {key: item for key, item in value.items() if key != "receipt_digest"}
    if (set(value) != _SANDBOX_BOOTSTRAP_FIELDS or value.get("schema_id") != HOST_SANDBOX_BOOTSTRAP_SCHEMA_ID
            or value.get("preflight_receipt_digest") != preflight_receipt_digest
            or _DIGEST.fullmatch(preflight_receipt_digest) is None
            or value.get("registry_projection") != projection
            or value.get("receipt_digest") != canonical_digest(payload)):
        raise HostSupervisionError("host_sandbox_bootstrap_receipt_invalid", "bootstrap receipt invalid")
    return value


def bootstrap_supervised_host_sandbox_image(repository_provider: SQLiteRepositoryProvider, runner: object, *, binding: SandboxBootstrapBinding) -> dict[str, Any]:
    preflight_receipt_digest = binding[0]
    preflight = runner.preflight()
    if not bool(getattr(preflight, "ok", False)):
        raise HostSupervisionError("host_sandbox_runtime_identity_missing", "sandbox preflight failed")
    identity = _validated_sandbox_runtime_identity(getattr(preflight, "runtime_identity", None), binding)
    runner.pinned_runtime_identity = dict(identity)
    repeated_preflight = runner.preflight()
    if not bool(getattr(repeated_preflight, "ok", False)):
        raise HostSupervisionError("host_sandbox_runtime_identity_drift", "sandbox preflight drifted")
    _validated_sandbox_runtime_identity(getattr(repeated_preflight, "runtime_identity", None), binding)
    projection = _sandbox_registry_projection(identity)
    with repository_provider.write() as scope:
        counts = tuple(scope.connection.execute("SELECT (SELECT COUNT(*) FROM sandbox_image_records), (SELECT COUNT(*) FROM sessions), (SELECT COUNT(*) FROM sandbox_workspace_records)").fetchone() or ())
        if counts != (0, 0, 0):
            raise HostSupervisionError("host_sandbox_bootstrap_registry_not_blank", "Host registries not blank")
        record = sandbox_image_record(image_ref=projection["image_ref"], image_digest=identity["image_digest"])
        scope.repositories.sandbox_images.save(record)
        if scope.repositories.sandbox_images.get(projection["image_ref"]) != record:
            raise HostSupervisionError("host_sandbox_bootstrap_reread_failed", "image reread failed")
        payload = {"schema_id": HOST_SANDBOX_BOOTSTRAP_SCHEMA_ID, "preflight_receipt_digest": preflight_receipt_digest, "runtime_identity": identity, "registry_projection": projection}
        receipt = {**payload, "receipt_digest": canonical_digest(payload)}
    return receipt


def host_supervision_contract_digest(
    *, timeout_seconds: float, startup_timeout_seconds: float,
    term_grace_seconds: float, kill_grace_seconds: float,
) -> str:
    bounds = (timeout_seconds, startup_timeout_seconds, term_grace_seconds, kill_grace_seconds)
    if (not all(math.isfinite(value) for value in bounds) or timeout_seconds <= 0
            or startup_timeout_seconds <= 0 or term_grace_seconds < 0
            or kill_grace_seconds < 0):
        raise ValueError("supervised Host bounds are invalid")
    return canonical_digest({
        **_CONTRACT, "timeout_seconds": timeout_seconds,
        "startup_timeout_seconds": startup_timeout_seconds,
        "term_grace_seconds": term_grace_seconds,
        "kill_grace_seconds": kill_grace_seconds,
    })


def _process_start_time_ticks(pid: int) -> int:
    content = Path(f"/proc/{pid}/stat").read_text()
    close = content.rfind(")")
    fields = content[close + 2 :].split()
    if close < 0 or len(fields) < 20:
        raise ValueError("process stat is truncated")
    return int(fields[19])


def _process_group_members(pgid: int) -> tuple[int, ...]:
    members: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            content = (entry / "stat").read_text()
            close = content.rfind(")")
            fields = content[close + 2 :].split()
            group, state = int(fields[2]), fields[0]
        except (OSError, ValueError, IndexError):
            continue
        if group == pgid and state != "Z":
            members.append(int(entry.name))
    return tuple(sorted(members))


def _sqlite_settlement(path: Path, *, read_only: bool) -> dict[str, object]:
    if not path.is_file():
        connection = sqlite3.connect(":memory:")
        try:
            mutation = project_mutation_local_settlement(connection).to_dict()
        finally:
            connection.close()
        return {"sqlite_checkpoint": "not_present", "sqlite_integrity": "not_present", **mutation}
    connection = (
        sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        if read_only else sqlite3.connect(path, timeout=5)
    )
    try:
        connection.execute("PRAGMA busy_timeout = 5000")
        if read_only:
            connection.execute("PRAGMA query_only = ON")
            checkpoint_status = "parent_read_only"
        else:
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint is None or int(checkpoint[0]) != 0:
                raise HostSupervisionError(
                    "host_sqlite_checkpoint_busy", "Host SQLite checkpoint remained busy"
                )
            checkpoint_status = "passed"
        if [str(row[0]) for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
            raise HostSupervisionError(
                "host_sqlite_integrity_failed", "Host SQLite integrity check failed"
            )
        try:
            mutation = project_mutation_local_settlement(connection).to_dict()
        except MutationLocalSettlementError as exc:
            raise HostSupervisionError(
                "host_mutation_settlement_failed", "Host mutation writers did not settle"
            ) from exc
        return {"sqlite_checkpoint": checkpoint_status, "sqlite_integrity": "passed", **mutation}
    finally:
        connection.close()


def _fsync_tree(path: Path) -> None:
    path.lstat()
    if path.is_symlink():
        raise HostSupervisionError(
            "host_root_symlink_detected", "declared Host root contains a symbolic link"
        )
    if path.is_dir():
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            _fsync_tree(child)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    elif path.is_file():
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    else:
        raise HostSupervisionError(
            "host_root_entry_invalid", "declared Host root contains an unsupported entry"
        )
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _settle_attempt_root(root: Path) -> dict[str, object]:
    settlement = _sqlite_settlement(root / "control-plane.sqlite3", read_only=False)
    for name in ("artifacts", "blobs", "sandboxes", "hpc-workspace", "evidence"):
        _fsync_tree(root / name)
    _fsync_tree(root)
    return {**settlement, "declared_root_sync": True}


def _send_frame(connection: Connection, payload: dict[str, object]) -> None:
    connection.send_bytes(canonical_json_bytes(payload))


def _receive_frame(connection: Connection, timeout: float) -> dict[str, Any]:
    if not connection.poll(timeout):
        raise HostSupervisionError(
            "host_supervision_frame_timeout", "supervised Host did not emit a bounded frame"
        )
    try:
        value = json.loads(connection.recv_bytes())
    except (EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostSupervisionError(
            "host_supervision_frame_invalid", "supervised Host lifecycle channel is invalid"
        ) from exc
    if not isinstance(value, dict):
        raise HostSupervisionError(
            "host_supervision_frame_invalid", "supervised Host frame must be an object"
        )
    return value


def _host_child_main(
    preflight_path: str, connection: Connection, epoch: str, startup_timeout: float
) -> None:
    os.setsid()
    preflight = load_attempt_preflight_receipt(Path(preflight_path), require_unstarted=True)
    slot, root = dict(preflight["slot"]), Path(preflight_path).parent.parent
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    listener: socket.socket | None = None
    failures: list[BaseException] = []
    try:
        settings = OpenZymeSettings.from_env()
        config = build_aox_cutover_effective_config(
            settings, ledger_path=Path(settings.test.live_llm.token_ledger_path)
        )
        if config.payload != preflight.get("effective_config"):
            raise HostSupervisionError(
                "host_effective_config_drift", "configured Host differs from preflight"
            )
        repository_provider = SQLiteRepositoryProvider(str(root / "control-plane.sqlite3"))
        sandbox_runner = PodmanPipelineSandboxRunner(workspace_root=root / "sandboxes")
        sandbox_bootstrap = bootstrap_supervised_host_sandbox_image(
            repository_provider, sandbox_runner, binding=supervised_host_sandbox_binding(preflight))
        dependencies = HostApiDependencies(
            foundation=build_configured_foundation(
                settings=config.settings, token_scenario_override="aox_blank_world_cutover"
            ),
            v3_repository_provider=repository_provider,
            v3_background_runtime_enabled=False,
            v3_pipeline_sandbox_runner=sandbox_runner,
            v3_tool_dispatch_precondition=AoxFinalizationToolPrecondition(
                session_id=str(slot["session_id"]),
                attempt_kind=str(slot["attempt_kind"]),
            ),
            v3_sandbox_workspace_root=root / "sandboxes",
            v3_artifact_blob_root=root / "blobs",
        )
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = int(listener.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(
            create_app(dependencies), host="127.0.0.1", port=port,
            log_level="warning", access_log=False, lifespan="on",
            timeout_graceful_shutdown=5,
        ))

        def run_server() -> None:
            try:
                assert server is not None and listener is not None
                server.run(sockets=[listener])
            except BaseException as exc:  # pragma: no cover - OS boundary
                failures.append(exc)

        thread = threading.Thread(target=run_server, name="aox-supervised-host")
        thread.start()
        deadline = time.monotonic() + startup_timeout
        while not server.started:
            if failures or not thread.is_alive():
                raise HostSupervisionError("host_startup_failed", "configured Host exited early")
            if time.monotonic() >= deadline:
                raise HostSupervisionError("host_startup_timeout", "configured Host was not ready")
            time.sleep(0.01)
        _send_frame(connection, {
            "schema_id": "aox_supervised_host_child_ready@2", "process_epoch": epoch,
            "child_pid": os.getpid(), "child_pgid": os.getpgrp(),
            "child_start_time_ticks": _process_start_time_ticks(os.getpid()),
            "base_url": f"http://127.0.0.1:{port}",
            "preflight_receipt_digest": preflight["receipt_digest"],
            "sandbox_bootstrap": sandbox_bootstrap,
        })
        while thread.is_alive():
            if not connection.poll(0.1):
                continue
            try:
                command = connection.recv_bytes()
            except EOFError:
                command = b"stop"
            if command != b"stop":
                raise HostSupervisionError(
                    "host_supervision_command_invalid", "supervised Host accepts only stop"
                )
            server.should_exit = True
            break
        thread.join(timeout=10)
        if thread.is_alive() or failures:
            code = "host_shutdown_timeout" if thread.is_alive() else "host_runtime_failed"
            raise HostSupervisionError(code, "configured Host did not retire normally")
        terminal: dict[str, object] = {
            "schema_id": "aox_supervised_host_child_terminal@1",
            "process_epoch": epoch, "outcome": "normal",
            "settlement": _settle_attempt_root(root),
        }
    except BaseException as exc:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5)
        terminal = {
            "schema_id": "aox_supervised_host_child_terminal@1",
            "process_epoch": epoch, "outcome": "failed",
            "failure_code": str(getattr(exc, "code", None) or "host_supervision_child_failed"),
            "failure_type": type(exc).__name__,
        }
        terminal["terminal_digest"] = canonical_digest(terminal)
        try:
            _send_frame(connection, terminal)
        except (BrokenPipeError, EOFError, OSError):
            pass
        raise
    else:
        terminal["terminal_digest"] = canonical_digest(terminal)
        _send_frame(connection, terminal)
    finally:
        if listener is not None:
            listener.close()
        connection.close()


def _retire_process_group(
    process: multiprocessing.Process, *, pgid: int | None,
    term_grace_seconds: float, kill_grace_seconds: float,
) -> bool:
    def members() -> tuple[int, ...]:
        return () if pgid is None else _process_group_members(pgid)

    for force, grace in ((False, term_grace_seconds), (True, kill_grace_seconds)):
        if not (process.is_alive() or members()):
            break
        try:
            if pgid is not None:
                os.killpg(pgid, signal.SIGKILL if force else signal.SIGTERM)
            elif force:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            pass
        process.join(timeout=grace)
    process.join(timeout=0)
    return process.exitcode is not None and not members()


def _receipt_path(preflight_path: Path, filename: str) -> Path:
    if preflight_path.name != ATTEMPT_PREFLIGHT_FILENAME:
        raise HostSupervisionError(
            "host_preflight_path_invalid", "Host supervision requires canonical preflight"
        )
    return preflight_path.parent / filename


def _publish(path: Path, payload: Mapping[str, Any]) -> None:
    publish_private_canonical_authority(
        path, canonical_json_bytes(dict(payload)) + b"\n"
    )


@dataclass(slots=True)
class SupervisedHostLease:
    preflight_path: Path
    preflight: dict[str, Any]
    process: multiprocessing.Process
    connection: Connection
    process_epoch: str
    child_pgid: int
    child_start_time_ticks: int
    startup_receipt: dict[str, Any]
    timeout_seconds: float
    startup_timeout_seconds: float
    term_grace_seconds: float
    kill_grace_seconds: float
    started_at_monotonic: float
    shutdown_reason: str = "operator_stop"
    supervision_receipt: dict[str, Any] | None = None

    def wait(self) -> None:
        deadline = self.started_at_monotonic + self.timeout_seconds
        while self.process.is_alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.shutdown_reason = "child_exit" if not self.process.is_alive() else "authority_deadline"

    def stop(self) -> dict[str, Any]:
        if self.supervision_receipt is not None:
            return self.supervision_receipt
        if self.process.is_alive():
            try:
                self.connection.send_bytes(b"stop")
            except (BrokenPipeError, EOFError, OSError):
                pass
        try:
            terminal = _receive_frame(self.connection, self.term_grace_seconds + 10)
        except HostSupervisionError:
            terminal = None
        self.process.join(timeout=self.term_grace_seconds)
        retired = _retire_process_group(
            self.process, pgid=self.child_pgid,
            term_grace_seconds=self.term_grace_seconds,
            kill_grace_seconds=self.kill_grace_seconds,
        )
        try:
            self.supervision_receipt = self._seal(terminal, retired)
            return self.supervision_receipt
        finally:
            self.connection.close()

    def _seal(self, terminal: object, retired: bool) -> dict[str, Any]:
        slot = dict(self.preflight["slot"])
        settlement = dict(terminal.get("settlement") or {}) if isinstance(terminal, dict) else {}
        payload = (
            {key: item for key, item in terminal.items() if key != "terminal_digest"}
            if isinstance(terminal, dict) else {}
        )
        valid_terminal = all((
            isinstance(terminal, dict),
            isinstance(terminal, dict)
            and terminal.get("schema_id") == "aox_supervised_host_child_terminal@1",
            isinstance(terminal, dict) and terminal.get("process_epoch") == self.process_epoch,
            isinstance(terminal, dict) and terminal.get("outcome") == "normal",
            isinstance(terminal, dict)
            and terminal.get("terminal_digest") == canonical_digest(payload),
            self.process.exitcode == 0, retired,
            self.shutdown_reason in {"operator_stop", "authority_deadline"},
        ))
        try:
            parent = _sqlite_settlement(
                self.preflight_path.parent.parent / "control-plane.sqlite3", read_only=True
            )
        except Exception:
            parent = {}
        mutation_fields = (
            "schema_id", "snapshot_digest", "observed_row_count",
            "nonterminal_scope_count", "active_writer_count",
        )
        revalidated = valid_terminal and parent.get("active_writer_count") == 0 and all(
            parent.get(field) == settlement.get(field) for field in mutation_fields
        )
        if not revalidated:
            slot_claim = dict(self.preflight["slot_claim"])
            failure = {
                "schema_id": HOST_SUPERVISION_FATAL_SCHEMA_ID,
                "launch_id": slot_claim.get("launch_id"),
                "attempt_kind": slot.get("attempt_kind"),
                "authority_policy_digest": slot.get("authority_policy_digest"),
                "preflight_receipt_digest": self.preflight["receipt_digest"],
                "process_epoch": self.process_epoch,
                "failure_code": "host_local_settlement_unproven",
                "child_exit_code": self.process.exitcode,
                "descendant_retirement_proven": retired,
                "terminal_frame_digest": (
                    terminal.get("terminal_digest") if isinstance(terminal, dict) else None
                ),
                "external_outcome": "unknown", "next_attempt_blocked": True,
            }
            failure["fatal_digest"] = canonical_digest(failure)
            _publish(_receipt_path(self.preflight_path, HOST_SUPERVISION_FATAL_FILENAME), failure)
            raise HostSupervisionError(
                "host_local_settlement_unproven", "supervised Host retirement is unproven"
            )
        slot_claim = dict(self.preflight["slot_claim"])
        receipt_payload = {
            "schema_id": HOST_SUPERVISION_RECEIPT_SCHEMA_ID,
            "mode": "policy_free_public_host", "launch_id": slot_claim["launch_id"],
            "attempt_kind": slot["attempt_kind"], "session_id": slot["session_id"],
            "root_ref": slot["root_ref"],
            "authority_policy_digest": slot["authority_policy_digest"],
            "campaign_id": self.preflight["campaign_id"],
            "preflight_receipt_digest": self.preflight["receipt_digest"],
            "host_startup_receipt_digest": self.startup_receipt["receipt_digest"],
            "process_epoch": self.process_epoch, "shutdown_reason": self.shutdown_reason,
            "child_exit_code": self.process.exitcode, "local_state_settled": True,
            "descendant_retirement_proven": True, "parent_snapshot_revalidated": True,
            "mutation_authority_schema_id": settlement["schema_id"],
            "mutation_authority_snapshot_digest": settlement["snapshot_digest"],
            "mutation_authority_observed_row_count": settlement["observed_row_count"],
            "nonterminal_mutation_scope_count": settlement["nonterminal_scope_count"],
            "active_mutation_writer_count": settlement["active_writer_count"],
            "sqlite_checkpoint": settlement["sqlite_checkpoint"],
            "sqlite_integrity": settlement["sqlite_integrity"],
            "declared_root_sync": settlement["declared_root_sync"],
            "terminal_frame_digest": terminal["terminal_digest"],
            "timeout_seconds": self.timeout_seconds,
            "startup_timeout_seconds": self.startup_timeout_seconds,
            "term_grace_seconds": self.term_grace_seconds,
            "kill_grace_seconds": self.kill_grace_seconds,
            "supervisor_contract_digest": host_supervision_contract_digest(
                timeout_seconds=self.timeout_seconds,
                startup_timeout_seconds=self.startup_timeout_seconds,
                term_grace_seconds=self.term_grace_seconds,
                kill_grace_seconds=self.kill_grace_seconds,
            ),
            "retired_at": datetime.now(UTC).isoformat(),
        }
        receipt = {**receipt_payload, "receipt_digest": canonical_digest(receipt_payload)}
        _publish(_receipt_path(self.preflight_path, HOST_SUPERVISION_FILENAME), receipt)
        return receipt


@contextmanager
def supervised_attempt_host(
    preflight_path: Path, *, startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    term_grace_seconds: float = DEFAULT_TERM_GRACE_SECONDS,
    kill_grace_seconds: float = DEFAULT_KILL_GRACE_SECONDS,
) -> Iterator[SupervisedHostLease]:
    if (os.name != "posix" or not Path("/proc/self/stat").is_file()
            or not hasattr(os, "setsid") or not hasattr(os, "killpg")):
        raise HostSupervisionError(
            "host_supervision_platform_unsupported", "supervised AOX Host requires POSIX /proc"
        )
    path = preflight_path.expanduser().resolve(strict=True)
    preflight = load_attempt_preflight_receipt(path, require_unstarted=True)
    slot = dict(preflight["slot"])
    timeout = float(dict(slot["authority_policy"])["max_wall_time_seconds"])
    host_supervision_contract_digest(
        timeout_seconds=timeout, startup_timeout_seconds=startup_timeout_seconds,
        term_grace_seconds=term_grace_seconds, kill_grace_seconds=kill_grace_seconds,
    )
    spawn = multiprocessing.get_context("spawn")
    parent, child = spawn.Pipe(duplex=True)
    epoch = uuid4().hex
    process = spawn.Process(
        target=_host_child_main, args=(str(path), child, epoch, startup_timeout_seconds),
        name=f"aox-host-{preflight['slot_claim']['launch_id']}",
    )
    process.start()
    child.close()
    if process.pid is None:
        parent.close()
        raise HostSupervisionError("host_spawn_failed", "supervised Host has no identity")
    pgid: int | None = None
    try:
        ready = _receive_frame(parent, startup_timeout_seconds)
        if ready.get("schema_id") == "aox_supervised_host_child_terminal@1" and ready.get("outcome") == "failed":
            raise HostSupervisionError(
                str(ready.get("failure_code") or "host_supervision_child_failed"), "supervised Host failed before child-ready")
        pgid, child_pid = int(ready.get("child_pgid") or 0), int(ready.get("child_pid") or 0)
        child_start = int(ready.get("child_start_time_ticks") or 0)
        if not all((
            ready.get("schema_id") == "aox_supervised_host_child_ready@2",
            ready.get("process_epoch") == epoch,
            ready.get("preflight_receipt_digest") == preflight["receipt_digest"],
            child_pid == process.pid, pgid == process.pid,
            os.getpgid(process.pid) == process.pid,
            child_start == _process_start_time_ticks(process.pid),
            str(ready.get("base_url") or "").startswith("http://127.0.0.1:"),
        )):
            raise HostSupervisionError(
                "host_process_identity_unproven", "Host readiness has the wrong identity"
            )
        sandbox_bootstrap = validate_supervised_host_sandbox_bootstrap(
            ready.get("sandbox_bootstrap"), binding=supervised_host_sandbox_binding(preflight))
        slot_claim = dict(preflight["slot_claim"])
        startup_payload = {
            "schema_id": HOST_STARTUP_SCHEMA_ID, "base_url": ready["base_url"],
            "launch_id": slot_claim["launch_id"], "attempt_kind": slot["attempt_kind"],
            "session_id": slot["session_id"], "root_ref": slot["root_ref"],
            "authority_policy_digest": slot["authority_policy_digest"],
            "campaign_id": preflight["campaign_id"],
            "preflight_receipt_digest": preflight["receipt_digest"],
            "process_epoch": epoch, "child_pid": child_pid, "child_pgid": pgid,
            "child_start_time_ticks": child_start, "timeout_seconds": timeout,
            "sandbox_bootstrap": sandbox_bootstrap,
            "started_at": datetime.now(UTC).isoformat(),
        }
        startup = {**startup_payload, "receipt_digest": canonical_digest(startup_payload)}
        _publish(_receipt_path(path, HOST_STARTUP_FILENAME), startup)
        lease = SupervisedHostLease(
            preflight_path=path, preflight=preflight, process=process, connection=parent,
            process_epoch=epoch, child_pgid=pgid, child_start_time_ticks=child_start,
            startup_receipt=startup, timeout_seconds=timeout,
            startup_timeout_seconds=startup_timeout_seconds,
            term_grace_seconds=term_grace_seconds, kill_grace_seconds=kill_grace_seconds,
            started_at_monotonic=time.monotonic(),
        )
        try:
            yield lease
        finally:
            lease.stop()
    except Exception:
        retired = _retire_process_group(
            process, pgid=pgid, term_grace_seconds=term_grace_seconds,
            kill_grace_seconds=kill_grace_seconds,
        )
        parent.close()
        if not retired:
            raise HostSupervisionError(
                "host_descendant_retirement_unproven", "Host descendants did not retire"
            ) from None
        raise


def validate_supervised_host_receipt(
    receipt: object, *, launch_id: str, attempt_kind: str,
    session_id: str, root_ref: str, campaign_id: str,
    authority_policy_digest: str,
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise CutoverEvidenceError(
            "host_supervision_receipt_missing",
            "eligible AOX evidence requires supervised Host retirement",
        )
    value = dict(receipt)
    payload = {key: item for key, item in value.items() if key != "receipt_digest"}
    try:
        contract = host_supervision_contract_digest(
            timeout_seconds=float(value["timeout_seconds"]),
            startup_timeout_seconds=float(value["startup_timeout_seconds"]),
            term_grace_seconds=float(value["term_grace_seconds"]),
            kill_grace_seconds=float(value["kill_grace_seconds"]),
        )
    except (KeyError, TypeError, ValueError):
        contract = None
    valid = all((
        set(value) == _RECEIPT_FIELDS,
        value.get("schema_id") == HOST_SUPERVISION_RECEIPT_SCHEMA_ID,
        value.get("mode") == "policy_free_public_host",
        value.get("launch_id") == launch_id,
        value.get("attempt_kind") == attempt_kind,
        value.get("session_id") == session_id,
        value.get("root_ref") == root_ref,
        value.get("campaign_id") == campaign_id,
        value.get("authority_policy_digest") == authority_policy_digest,
        bool(value.get("process_epoch")),
        all(_DIGEST.fullmatch(str(value.get(name) or "")) for name in (
            "authority_policy_digest", "preflight_receipt_digest",
            "host_startup_receipt_digest", "mutation_authority_snapshot_digest",
            "terminal_frame_digest", "supervisor_contract_digest", "receipt_digest",
        )),
        value.get("shutdown_reason") in {"operator_stop", "authority_deadline"},
        value.get("child_exit_code") == 0,
        value.get("local_state_settled") is True,
        value.get("descendant_retirement_proven") is True,
        value.get("parent_snapshot_revalidated") is True,
        value.get("mutation_authority_schema_id") == MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID,
        all(type(value.get(name)) is int and value[name] >= 0 for name in (
            "mutation_authority_observed_row_count", "nonterminal_mutation_scope_count",
            "active_mutation_writer_count",
        )),
        value.get("nonterminal_mutation_scope_count") == 0,
        value.get("active_mutation_writer_count") == 0,
        value.get("sqlite_checkpoint") in {"passed", "not_present"},
        value.get("sqlite_integrity") in {"passed", "not_present"},
        value.get("declared_root_sync") is True, bool(value.get("retired_at")),
        value.get("supervisor_contract_digest") == contract,
        value.get("receipt_digest") == canonical_digest(payload),
    ))
    if not valid:
        raise CutoverEvidenceError(
            "host_supervision_receipt_invalid",
            "supervised Host receipt does not prove exact local retirement",
            details={"identity": "product_path.attempt_supervision"},
        )
    return value
