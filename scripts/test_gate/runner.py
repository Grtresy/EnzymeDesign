"""Bounded process execution and no-replace evidence publication."""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Mapping, Sequence


class TestGateRunnerError(RuntimeError):
    """Raised when test-gate process or publication invariants fail."""

    __test__ = False


@dataclass(frozen=True)
class StreamCapture:
    digest: str
    total_bytes: int
    tail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "total_bytes": self.total_bytes,
            "tail": self.tail,
        }


@dataclass(frozen=True)
class ProcessResult:
    argv: tuple[str, ...]
    cwd: str
    outcome: str
    exit_code: int | None
    started_monotonic_ns: int
    duration_ns: int
    stdout: StreamCapture
    stderr: StreamCapture
    timed_out: bool
    term_sent: bool
    kill_sent: bool
    error: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "argv": list(self.argv),
            "cwd": self.cwd,
            "outcome": self.outcome,
            "exit_code": self.exit_code,
            "started_monotonic_ns": self.started_monotonic_ns,
            "duration_ns": self.duration_ns,
            "stdout": self.stdout.as_dict(),
            "stderr": self.stderr.as_dict(),
            "timed_out": self.timed_out,
            "term_sent": self.term_sent,
            "kill_sent": self.kill_sent,
            "error": self.error,
        }


def validate_new_output_root(repo_root: Path, output_root: Path) -> Path:
    """Validate an absolute, checkout-external path that does not yet exist."""

    if not output_root.is_absolute():
        raise TestGateRunnerError("output root must be absolute")
    try:
        resolved_repo = repo_root.resolve(strict=True)
    except OSError as exc:
        raise TestGateRunnerError(f"repository root does not exist: {repo_root}") from exc
    if not resolved_repo.is_dir():
        raise TestGateRunnerError(
            f"repository root is not a directory: {resolved_repo}"
        )
    if output_root.exists() or output_root.is_symlink():
        raise TestGateRunnerError(f"output root already exists: {output_root}")
    unresolved_candidate = output_root.resolve(strict=False)
    try:
        lexically_inside_checkout = (
            os.path.commonpath((str(resolved_repo), str(unresolved_candidate)))
            == str(resolved_repo)
        )
    except ValueError as exc:
        raise TestGateRunnerError(f"cannot compare output and repository roots: {exc}") from exc
    if lexically_inside_checkout:
        raise TestGateRunnerError(
            f"output root must be outside the checkout: {unresolved_candidate}"
        )
    try:
        resolved_parent = output_root.parent.resolve(strict=True)
    except OSError as exc:
        raise TestGateRunnerError(
            f"output root parent must already exist: {output_root.parent}"
        ) from exc
    if not resolved_parent.is_dir():
        raise TestGateRunnerError(
            f"output root parent is not a directory: {resolved_parent}"
        )
    candidate = resolved_parent / output_root.name
    return candidate


def create_new_output_root(repo_root: Path, output_root: Path) -> Path:
    """Create one validated output root without replacing an existing path."""

    validated = validate_new_output_root(repo_root, output_root)
    try:
        validated.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise TestGateRunnerError(
            f"output root appeared before creation: {validated}"
        ) from exc
    except OSError as exc:
        raise TestGateRunnerError(f"cannot create output root {validated}: {exc}") from exc
    return validated


def publish_no_replace(path: Path, data: bytes) -> None:
    """Publish bytes exactly once with durable no-replace semantics."""

    if not path.is_absolute():
        raise TestGateRunnerError("publication path must be absolute")
    if not isinstance(data, bytes):
        raise TestGateRunnerError("publication payload must be bytes")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise TestGateRunnerError(
            f"refusing to replace existing evidence: {path}"
        ) from exc
    except OSError as exc:
        raise TestGateRunnerError(f"cannot create evidence file {path}: {exc}") from exc
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise TestGateRunnerError(f"short write while publishing {path}")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    try:
        parent_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except OSError as exc:
        raise TestGateRunnerError(
            f"evidence was written but parent sync failed for {path}: {exc}"
        ) from exc


def _capture_stream(handle: BinaryIO, *, tail_bytes: int) -> StreamCapture:
    handle.seek(0)
    digest = hashlib.sha256()
    total_bytes = 0
    tail = bytearray()
    while chunk := handle.read(1024 * 1024):
        digest.update(chunk)
        total_bytes += len(chunk)
        if tail_bytes:
            tail.extend(chunk)
            if len(tail) > tail_bytes:
                del tail[:-tail_bytes]
    return StreamCapture(
        digest=f"sha256:{digest.hexdigest()}",
        total_bytes=total_bytes,
        tail=bytes(tail).decode("utf-8", errors="replace"),
    )


def _signal_process_group(process: subprocess.Popen[bytes], requested: signal.Signals) -> bool:
    if process.poll() is not None:
        return False
    try:
        os.killpg(process.pid, requested)
    except ProcessLookupError:
        return False
    except OSError as exc:
        raise TestGateRunnerError(
            f"cannot send {requested.name} to process group {process.pid}: {exc}"
        ) from exc
    return True


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str] | None = None,
    timeout_seconds: float,
    termination_grace_seconds: float = 1.0,
    tail_bytes: int = 64 * 1024,
) -> ProcessResult:
    """Run one command in a fresh process group with bounded retained output."""

    normalized_argv = tuple(argv)
    if not normalized_argv or any(
        not isinstance(argument, str) or not argument for argument in normalized_argv
    ):
        raise TestGateRunnerError("argv must contain nonempty strings")
    if timeout_seconds <= 0:
        raise TestGateRunnerError("timeout_seconds must be positive")
    if termination_grace_seconds < 0:
        raise TestGateRunnerError("termination_grace_seconds must not be negative")
    if type(tail_bytes) is not int or tail_bytes < 0:
        raise TestGateRunnerError("tail_bytes must be a nonnegative integer")
    try:
        resolved_cwd = cwd.resolve(strict=True)
    except OSError as exc:
        raise TestGateRunnerError(f"command cwd does not exist: {cwd}") from exc
    if not resolved_cwd.is_dir():
        raise TestGateRunnerError(f"command cwd is not a directory: {resolved_cwd}")

    started = time.monotonic_ns()
    term_sent = False
    kill_sent = False
    timed_out = False
    error: str | None = None
    exit_code: int | None = None
    with tempfile.TemporaryFile(mode="w+b") as stdout_file:
        with tempfile.TemporaryFile(mode="w+b") as stderr_file:
            try:
                process = subprocess.Popen(
                    normalized_argv,
                    cwd=resolved_cwd,
                    env=None if environment is None else dict(environment),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    start_new_session=True,
                )
            except OSError as exc:
                process = None
                error = f"{type(exc).__name__}:{exc.errno}:{exc.strerror}"
            if process is not None:
                try:
                    exit_code = process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    term_sent = _signal_process_group(process, signal.SIGTERM)
                    try:
                        exit_code = process.wait(timeout=termination_grace_seconds)
                    except subprocess.TimeoutExpired:
                        kill_sent = _signal_process_group(process, signal.SIGKILL)
                        exit_code = process.wait()
            finished = time.monotonic_ns()
            stdout_capture = _capture_stream(stdout_file, tail_bytes=tail_bytes)
            stderr_capture = _capture_stream(stderr_file, tail_bytes=tail_bytes)

    if error is not None:
        outcome = "error"
    elif timed_out:
        outcome = "timeout"
    elif exit_code == 0:
        outcome = "pass"
    else:
        outcome = "fail"
    return ProcessResult(
        argv=normalized_argv,
        cwd=str(resolved_cwd),
        outcome=outcome,
        exit_code=exit_code,
        started_monotonic_ns=started,
        duration_ns=finished - started,
        stdout=stdout_capture,
        stderr=stderr_capture,
        timed_out=timed_out,
        term_sent=term_sent,
        kill_sent=kill_sent,
        error=error,
    )
