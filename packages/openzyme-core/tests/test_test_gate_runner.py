from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.runner import (  # noqa: E402
    TestGateRunnerError,
    create_new_output_root,
    publish_no_replace,
    run_command,
    validate_new_output_root,
)


def test_output_root_must_be_absolute_new_and_outside_checkout(
    tmp_path: Path,
) -> None:
    with pytest.raises(TestGateRunnerError, match="absolute"):
        validate_new_output_root(REPOSITORY_ROOT, Path("relative-output"))
    with pytest.raises(TestGateRunnerError, match="outside the checkout"):
        validate_new_output_root(
            REPOSITORY_ROOT,
            REPOSITORY_ROOT / "candidate-output",
        )
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(TestGateRunnerError, match="already exists"):
        validate_new_output_root(REPOSITORY_ROOT, existing)

    candidate = tmp_path / "new-output"
    assert create_new_output_root(REPOSITORY_ROOT, candidate) == candidate
    assert candidate.is_dir()


def test_publication_is_no_replace_and_durable(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    payload = b'{"status":"diagnostic"}\n'
    publish_no_replace(target, payload)
    assert target.read_bytes() == payload
    with pytest.raises(TestGateRunnerError, match="refusing to replace"):
        publish_no_replace(target, b"replacement")
    assert target.read_bytes() == payload


def test_process_output_retains_only_bounded_tail_and_full_digest(
    tmp_path: Path,
) -> None:
    stdout_text = "x" * 512 + "STDOUT-END\n"
    stderr_text = "y" * 384 + "STDERR-END\n"
    stdout = stdout_text.encode()
    stderr = stderr_text.encode()
    result = run_command(
        (
            sys.executable,
            "-c",
            (
                "import sys;"
                f"sys.stdout.write({stdout_text!r});"
                f"sys.stderr.write({stderr_text!r})"
            ),
        ),
        cwd=tmp_path,
        timeout_seconds=5,
        tail_bytes=32,
    )

    assert result.outcome == "pass"
    assert result.exit_code == 0
    assert result.duration_ns > 0
    assert result.stdout.total_bytes == len(stdout)
    assert result.stderr.total_bytes == len(stderr)
    assert result.stdout.digest == f"sha256:{hashlib.sha256(stdout).hexdigest()}"
    assert result.stderr.digest == f"sha256:{hashlib.sha256(stderr).hexdigest()}"
    assert result.stdout.tail.endswith("STDOUT-END\n")
    assert result.stderr.tail.endswith("STDERR-END\n")
    assert len(result.stdout.tail.encode()) <= 32
    assert len(result.stderr.tail.encode()) <= 32


def test_timeout_sends_term_and_allows_bounded_graceful_retirement(
    tmp_path: Path,
) -> None:
    result = run_command(
        (
            sys.executable,
            "-c",
            (
                "import signal,time;"
                "signal.signal(signal.SIGTERM,lambda *_:raise_exit());"
                "raise_exit=lambda:exit(23);"
                "print('ready',flush=True);"
                "time.sleep(30)"
            ),
        ),
        cwd=tmp_path,
        timeout_seconds=0.25,
        termination_grace_seconds=0.5,
    )

    assert result.outcome == "timeout"
    assert result.timed_out is True
    assert result.term_sent is True
    assert result.kill_sent is False
    assert result.exit_code == 23
    assert result.duration_ns < 2_000_000_000


def test_timeout_escalates_to_kill_when_process_ignores_term(tmp_path: Path) -> None:
    result = run_command(
        (
            sys.executable,
            "-c",
            (
                "import signal,time;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                "print('ready',flush=True);"
                "time.sleep(30)"
            ),
        ),
        cwd=tmp_path,
        timeout_seconds=0.25,
        termination_grace_seconds=0.1,
    )

    assert result.outcome == "timeout"
    assert result.timed_out is True
    assert result.term_sent is True
    assert result.kill_sent is True
    assert result.exit_code is not None and result.exit_code < 0
    assert result.duration_ns < 2_000_000_000
