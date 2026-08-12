from __future__ import annotations

from dataclasses import dataclass
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import sandbox_image_record
from openzyme_core.repositories import SandboxImageRecordRepository
from openzyme_domain import SandboxImageCompatibility
from openzyme_engines import PodmanSandboxPreflight
from openzyme_host_api import aox_host_supervision as host_supervision
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_host_supervision import HostSupervisionError
from openzyme_host_api.aox_host_supervision import (
    bootstrap_supervised_host_sandbox_image,
)
from openzyme_host_api.aox_host_supervision import (
    validate_supervised_host_sandbox_bootstrap,
)


IMAGE_DIGEST = "sha256:" + "a" * 64
SDK_DIGEST = "sha256:" + "b" * 64
PREFLIGHT_DIGEST = "sha256:" + "c" * 64
START_CLAIM_DIGEST = "sha256:" + "d" * 64


def _identity(**changes: str) -> dict[str, str]:
    payload = {
        "configured_image_ref": "localhost/openzyme-pipeline-sandbox:dev",
        "immutable_image_ref": IMAGE_DIGEST,
        "image_digest": IMAGE_DIGEST,
        "pipeline_sdk_digest": SDK_DIGEST,
        "sandbox_protocol_version": "s10",
    }
    payload.update({key: value for key, value in changes.items() if key in payload})
    identity = {**payload, "runtime_identity_digest": canonical_digest(payload)}
    if "runtime_identity_digest" in changes:
        identity["runtime_identity_digest"] = changes["runtime_identity_digest"]
    return identity


@dataclass(slots=True)
class _Runner:
    identities: list[dict[str, str] | None]
    pinned_runtime_identity: dict[str, str] | None = None
    respect_pin: bool = True
    calls: int = 0

    def preflight(self) -> PodmanSandboxPreflight:
        identity = self.identities[min(self.calls, len(self.identities) - 1)]
        self.calls += 1
        if identity is None:
            return PodmanSandboxPreflight(
                False,
                "missing",
                failure_code="podman_rootless_preflight_failed",
            )
        if (
            self.respect_pin
            and self.pinned_runtime_identity is not None
            and identity != self.pinned_runtime_identity
        ):
            return PodmanSandboxPreflight(
                False,
                "drift",
                failure_code="sandbox_runtime_identity_drift",
            )
        return PodmanSandboxPreflight(True, "ready", dict(identity))


def _provider(tmp_path: Path) -> SQLiteRepositoryProvider:
    return SQLiteRepositoryProvider(str(tmp_path / "control-plane.sqlite3"))


def _bootstrap(
    provider: SQLiteRepositoryProvider,
    runner: _Runner,
    *,
    expected_image_digest: str = IMAGE_DIGEST,
    expected_sdk_digest: str = SDK_DIGEST,
) -> dict[str, object]:
    return bootstrap_supervised_host_sandbox_image(
        provider,
        runner,
        binding=(PREFLIGHT_DIGEST, expected_image_digest, expected_sdk_digest),
    )


def _failed_child_frame(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_id": "aox_supervised_host_child_pre_ready_failure@2",
        "process_epoch": "epoch-1",
        "attempt_start_claim_digest": START_CLAIM_DIGEST,
        "outcome": "failed",
        "failure_code": "host_sandbox_runtime_identity_missing",
        "failure_type": "HostSupervisionError",
        "failure_stage": "sandbox_bootstrap_pre_registry",
        "sandbox_preflight_failure_code": "podman_rootless_preflight_failed",
        "child_pid": 1234,
        "child_pgid": 1234,
        "child_start_time_ticks": 5678,
    }
    payload.update(changes)
    return {**payload, "terminal_digest": canonical_digest(payload)}


def _pre_ready_fault_child(
    connection: Connection, process_epoch: str, start_claim_digest: str
) -> None:
    os.setsid()
    pid = os.getpid()
    payload: dict[str, object] = {
        "schema_id": "aox_supervised_host_child_pre_ready_failure@2",
        "process_epoch": process_epoch,
        "attempt_start_claim_digest": start_claim_digest,
        "outcome": "failed",
        "failure_code": "host_sandbox_runtime_identity_missing",
        "failure_type": "HostSupervisionError",
        "failure_stage": "sandbox_bootstrap_pre_registry",
        "sandbox_preflight_failure_code": "podman_rootless_preflight_failed",
        "child_pid": pid,
        "child_pgid": os.getpgrp(),
        "child_start_time_ticks": host_supervision._process_start_time_ticks(pid),
    }
    frame = {**payload, "terminal_digest": canonical_digest(payload)}
    connection.send_bytes(host_supervision.canonical_json_bytes(frame))
    if connection.poll(5):
        connection.recv_bytes()
    connection.close()
    raise SystemExit(17)


@pytest.mark.skipif(
    os.name != "posix" or not Path("/proc/self/stat").is_file(),
    reason="AOX supervised process identity requires POSIX /proc",
)
def test_pre_ready_child_frame_binds_real_process_and_retires_group() -> None:
    process_context = multiprocessing.get_context("fork")
    parent, child = process_context.Pipe(duplex=True)
    process_epoch = "epoch-real-process"
    process = process_context.Process(
        target=_pre_ready_fault_child,
        args=(child, process_epoch, START_CLAIM_DIGEST),
    )
    process.start()
    child.close()
    try:
        frame = host_supervision._receive_frame(parent, 5.0)
        validated = host_supervision._validated_child_pre_ready_failure(
            frame,
            process=process,
            process_epoch=process_epoch,
            attempt_start_claim_digest=START_CLAIM_DIGEST,
        )
        parent.send_bytes(b"settle-pre-ready-failure")
        process.join(timeout=5)
        assert process.exitcode == 17
        assert host_supervision._retire_process_group(
            process,
            pgid=int(validated["child_pgid"]),
            term_grace_seconds=0.1,
            kill_grace_seconds=0.1,
        ) is True
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        parent.close()


def test_pre_ready_child_frame_binds_exact_live_process_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = SimpleNamespace(pid=1234, is_alive=lambda: True)
    monkeypatch.setattr(host_supervision.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        host_supervision,
        "_process_start_time_ticks",
        lambda pid: 5678,
    )
    frame = _failed_child_frame()

    assert host_supervision._validated_child_pre_ready_failure(
        frame,
        process=process,
        process_epoch="epoch-1",
        attempt_start_claim_digest=START_CLAIM_DIGEST,
    ) == frame

    drifted = _failed_child_frame(child_pgid=4321)
    with pytest.raises(HostSupervisionError) as error:
        host_supervision._validated_child_pre_ready_failure(
            drifted,
            process=process,
            process_epoch="epoch-1",
            attempt_start_claim_digest=START_CLAIM_DIGEST,
        )
    assert error.value.code == "host_process_identity_unproven"


def test_supervised_host_bootstrap_atomically_installs_exact_immutable_record(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    runner = _Runner([_identity()])

    receipt = _bootstrap(provider, runner)

    assert validate_supervised_host_sandbox_bootstrap(
        receipt,
        binding=(PREFLIGHT_DIGEST, IMAGE_DIGEST, SDK_DIGEST),
    ) == receipt
    assert runner.pinned_runtime_identity == _identity()
    with provider.read() as scope:
        record = scope.repositories.sandbox_images.get_default()
        counts = tuple(
            scope.connection.execute(
                "SELECT (SELECT COUNT(*) FROM sessions), "
                "(SELECT COUNT(*) FROM sandbox_workspace_records)"
            ).fetchone()
        )
    assert record is not None
    assert record.image_ref == (
        "localhost/openzyme-pipeline-sandbox@" + IMAGE_DIGEST
    )
    assert record.sandbox_protocol_version == "s07"
    assert record.compatibility is SandboxImageCompatibility.COMPATIBLE
    assert counts == (0, 0)

    with pytest.raises(HostSupervisionError) as error:
        _bootstrap(provider, runner)
    assert error.value.code == "host_sandbox_bootstrap_registry_not_blank"


@pytest.mark.parametrize(
    ("runner", "image_digest", "sdk_digest", "code"),
    (
        (
            _Runner([None]),
            IMAGE_DIGEST,
            SDK_DIGEST,
            "host_sandbox_runtime_identity_missing",
        ),
        (
            _Runner([{key: value for key, value in _identity().items() if key != "immutable_image_ref"}]),
            IMAGE_DIGEST,
            SDK_DIGEST,
            "host_sandbox_runtime_identity_invalid",
        ),
        (
            _Runner([_identity(immutable_image_ref="sha256:" + "d" * 64)]),
            IMAGE_DIGEST,
            SDK_DIGEST,
            "host_sandbox_runtime_identity_invalid",
        ),
        (
            _Runner([_identity(runtime_identity_digest="sha256:" + "e" * 64)]),
            IMAGE_DIGEST,
            SDK_DIGEST,
            "host_sandbox_runtime_identity_invalid",
        ),
        (
            _Runner([_identity()]),
            "sha256:" + "d" * 64,
            SDK_DIGEST,
            "host_sandbox_runtime_identity_mismatch",
        ),
        (
            _Runner([_identity()]),
            IMAGE_DIGEST,
            "sha256:" + "e" * 64,
            "host_sandbox_runtime_identity_mismatch",
        ),
    ),
)
def test_supervised_host_bootstrap_rejects_missing_malformed_or_mismatched_identity(
    tmp_path: Path,
    runner: _Runner,
    image_digest: str,
    sdk_digest: str,
    code: str,
) -> None:
    provider = _provider(tmp_path)

    with pytest.raises(HostSupervisionError) as error:
        _bootstrap(
            provider,
            runner,
            expected_image_digest=image_digest,
            expected_sdk_digest=sdk_digest,
        )

    assert error.value.code == code
    if code == "host_sandbox_runtime_identity_missing":
        assert error.value.sandbox_preflight_failure_code == (
            "podman_rootless_preflight_failed"
        )
    with provider.read() as scope:
        count = scope.connection.execute(
            "SELECT COUNT(*) FROM sandbox_image_records"
        ).fetchone()[0]
    assert count == 0


@pytest.mark.parametrize("is_default", (True, False))
def test_supervised_host_bootstrap_rejects_any_preexisting_image_row(
    tmp_path: Path,
    is_default: bool,
) -> None:
    provider = _provider(tmp_path)
    with provider.write() as scope:
        scope.repositories.sandbox_images.save(
            sandbox_image_record(
                image_ref="example.invalid/sandbox@" + "sha256:" + "d" * 64,
                image_digest="sha256:" + "d" * 64,
                is_default=is_default,
            )
        )

    with pytest.raises(HostSupervisionError) as error:
        _bootstrap(provider, _Runner([_identity()]))

    assert error.value.code == "host_sandbox_bootstrap_registry_not_blank"


def test_supervised_host_bootstrap_rejects_preexisting_session_state(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    with provider.write() as scope:
        scope.connection.execute(
            "INSERT INTO sessions "
            "(session_id, project_id, title, objective, status, created_at, updated_at) "
            "VALUES ('existing', 'p', 't', 'o', 'active', 'now', 'now')"
        )

    with pytest.raises(HostSupervisionError) as error:
        _bootstrap(provider, _Runner([_identity()]))

    assert error.value.code == "host_sandbox_bootstrap_registry_not_blank"


def test_supervised_host_bootstrap_rejects_runner_drift_before_write(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    runner = _Runner(
        [_identity(), _identity(image_digest="sha256:" + "d" * 64)],
        respect_pin=False,
    )

    with pytest.raises(HostSupervisionError) as error:
        _bootstrap(provider, runner)

    assert error.value.code in {
        "host_sandbox_runtime_identity_invalid",
        "host_sandbox_runtime_identity_mismatch",
        "host_sandbox_runtime_identity_drift",
    }


def test_supervised_host_bootstrap_rolls_back_failed_reread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(tmp_path)
    monkeypatch.setattr(SandboxImageRecordRepository, "get", lambda self, image_ref: None)

    with pytest.raises(HostSupervisionError) as error:
        _bootstrap(provider, _Runner([_identity()]))

    assert error.value.code == "host_sandbox_bootstrap_reread_failed"
    with provider.read() as scope:
        count = scope.connection.execute(
            "SELECT COUNT(*) FROM sandbox_image_records"
        ).fetchone()[0]
    assert count == 0


def test_supervised_host_bootstrap_receipt_rejects_resealed_protocol_tamper(
    tmp_path: Path,
) -> None:
    receipt = _bootstrap(_provider(tmp_path), _Runner([_identity()]))
    tampered = {
        **receipt,
        "registry_projection": {
            **dict(receipt["registry_projection"]),
            "sandbox_protocol_version": "s10",
        },
    }
    payload = {key: value for key, value in tampered.items() if key != "receipt_digest"}
    tampered["receipt_digest"] = canonical_digest(payload)

    with pytest.raises(HostSupervisionError) as error:
        validate_supervised_host_sandbox_bootstrap(
            tampered,
            binding=(PREFLIGHT_DIGEST, IMAGE_DIGEST, SDK_DIGEST),
        )

    assert error.value.code == "host_sandbox_bootstrap_receipt_invalid"
