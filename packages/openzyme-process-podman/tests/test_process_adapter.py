from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceExecRequest
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_process_podman import MappingPodmanWorkspaceMountResolver
from openzyme_process_podman import PodmanDispatchError
from openzyme_process_podman import PodmanProcessIsolationAdapter
from openzyme_process_podman import PodmanWorkspaceMount
from openzyme_process_podman import PodmanWorkspaceProcessAdapter
from openzyme_process_podman import SupervisedProcessRequest
from openzyme_process_podman import SupervisedProcessResult
from openzyme_process_podman import SupervisedSubprocessExecutor
from openzyme_runtime_spi import IsolatedProcessState
from openzyme_runtime_spi import ProcessIsolationRequest
from openzyme_store_sqlite import SQLiteWorkspaceOperationLedger
from openzyme_store_sqlite import install_store_schema_for_offline_migration


class _Clock:
    def now_iso(self) -> str:
        return "2026-08-22T12:00:00+00:00"


def _ledger(
    connection: sqlite3.Connection | None = None,
) -> SQLiteWorkspaceOperationLedger:
    selected = connection or sqlite3.connect(":memory:")
    if selected.execute("PRAGMA user_version").fetchone()[0] == 0:
        install_store_schema_for_offline_migration(selected)
    return SQLiteWorkspaceOperationLedger(selected, _Clock())


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _binding() -> WorkspaceRuntimeBinding:
    return WorkspaceRuntimeBinding(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="member-1",
        generation=3,
        state_version=2,
        root_identity_digest=_digest("root"),
        provider_id="openzyme.workspace.git-lfs",
        target_id="local:host",
    )


def _mount() -> PodmanWorkspaceMount:
    return PodmanWorkspaceMount.create(
        workspace_id="workspace-1",
        session_id="session-1",
        owner_member_id="member-1",
        generation=3,
        state_version=2,
        root_identity_digest=_digest("root"),
        target_id="local:host",
        volume_id="workspace-volume-1",
        clone_logical_root="/workspace/repository",
        image_identity="registry.invalid/openzyme/agent@sha256:" + "a" * 64,
    )


def _isolation_request() -> ProcessIsolationRequest:
    mount = _mount()
    return ProcessIsolationRequest(
        request_id="operation-1.isolation",
        command_id="operation-1",
        session_id="session-1",
        agent_member_id="member-1",
        workspace=_binding(),
        process_epoch=5,
        authority_lease_id="authority-lease-1",
        authority_generation=2,
        authority_fence=7,
        argv=("python", "script.py"),
        cwd_relative="analysis",
        environment={"TOKEN": "secret-value"},
        secret_environment_keys=("TOKEN",),
        image_identity=mount.image_identity,
        mount_manifest_digest=mount.mount_manifest_digest,
        timeout_seconds=30,
        max_output_bytes=4_096,
        stdin=b"input",
    )


@dataclass
class FakeExecutor:
    calls: list[SupervisedProcessRequest]
    stdout: bytes = b"ok"
    stderr: bytes = b""
    returncode: int = 0
    timed_out: bool = False
    error: Exception | None = None

    def run(self, request: SupervisedProcessRequest) -> SupervisedProcessResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return SupervisedProcessResult(
            process_identity=request.process_identity,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=self.timed_out,
            retired=False,
            started_at="2026-08-19T00:00:00+00:00",
            ended_at="2026-08-19T00:00:01+00:00",
            duration_ms=1_000,
        )

    def retire(
        self,
        *,
        process_identity: str,
        process_epoch: int,
        authority_fence: int,
    ) -> SupervisedProcessResult:
        assert process_epoch == 5
        assert authority_fence == 7
        return SupervisedProcessResult(
            process_identity=process_identity,
            returncode=-15,
            stdout=b"",
            stderr=b"",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
            retired=True,
            started_at="2026-08-19T00:00:00+00:00",
            ended_at="2026-08-19T00:00:01+00:00",
            duration_ms=1_000,
        )


def _adapter(executor: FakeExecutor) -> PodmanProcessIsolationAdapter:
    return PodmanProcessIsolationAdapter(
        mount_resolver=MappingPodmanWorkspaceMountResolver(
            {"workspace-1": _mount()}
        ),
        deployment_network="openzyme-deployment",
        executor=executor,
    )


def test_podman_adapter_builds_exact_bounded_command_without_secret_argv() -> None:
    executor = FakeExecutor([], stdout=b"secret-value must be hidden")
    adapter = _adapter(executor)
    request = _isolation_request()

    receipt = adapter.execute(request)
    replay = adapter.execute(request)

    assert receipt is replay
    assert receipt.state is IsolatedProcessState.EXITED
    assert receipt.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert len(executor.calls) == 1
    command = executor.calls[0]
    assert command.argv[:5] == (
        "/usr/bin/podman",
        "run",
        "--rm",
        "--name",
        receipt.process_identity,
    )
    assert "workspace-volume-1" in " ".join(command.argv)
    assert "secret-value" not in command.argv
    assert command.environment == {"TOKEN": "secret-value"}
    assert command.stdin == b"input"
    assert command.timeout_seconds == 40
    assert receipt.stdout_summary == "[REDACTED] must be hidden"
    assert "secret-value" not in json.dumps(request.to_dict())
    assert request.to_dict()["environment_keys"] == ["TOKEN"]


def test_stale_mount_fails_no_effect_before_executor() -> None:
    executor = FakeExecutor([])
    adapter = PodmanProcessIsolationAdapter(
        mount_resolver=MappingPodmanWorkspaceMountResolver({}),
        deployment_network="openzyme-deployment",
        executor=executor,
    )

    receipt = adapter.execute(_isolation_request())

    assert receipt.state is IsolatedProcessState.FAILED
    assert receipt.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert receipt.failure is not None
    assert receipt.failure.error_code == "podman_workspace_mount_stale"
    assert executor.calls == []


@pytest.mark.parametrize(
    ("error", "certainty"),
    [
        (
            PodmanDispatchError(
                "podman_response_lost",
                "private failure",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            ),
            ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        ),
        (RuntimeError("unclassified private failure"), ExternalEffectCertainty.DISPATCH_IN_DOUBT),
    ],
)
def test_adapter_failure_never_retries_or_falls_back(
    error: Exception,
    certainty: ExternalEffectCertainty,
) -> None:
    executor = FakeExecutor([], error=error)
    receipt = _adapter(executor).execute(_isolation_request())

    assert len(executor.calls) == 1
    assert receipt.state is IsolatedProcessState.FAILED
    assert receipt.effect_certainty is certainty
    assert receipt.fallback_performed is False
    assert receipt.failure is not None
    assert receipt.failure.retry_eligibility.value == "reconcile_required"


def test_process_isolation_reconciliation_never_launches_replacement() -> None:
    executor = FakeExecutor([])
    adapter = _adapter(executor)
    request = _isolation_request()
    receipt = adapter.execute(request)

    reconciled = adapter.reconcile(request)
    restarted = _adapter(executor)
    pending = restarted.reconcile(request)

    assert reconciled is receipt
    assert len(executor.calls) == 1
    assert pending.state is IsolatedProcessState.FAILED
    assert pending.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert pending.failure is not None
    assert pending.failure.retry_eligibility.value == "reconcile_required"


def test_timeout_is_terminal_known_and_not_automatically_replayed() -> None:
    executor = FakeExecutor([], timed_out=True, returncode=124)
    adapter = _adapter(executor)
    request = _isolation_request()

    receipt = adapter.execute(request)
    replay = adapter.execute(request)

    assert receipt is replay
    assert len(executor.calls) == 1
    assert receipt.state is IsolatedProcessState.FAILED
    assert receipt.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert receipt.failure is not None
    assert receipt.failure.error_code == "podman_process_timeout"


def test_nonzero_exit_is_exact_terminal_receipt_not_provider_retry() -> None:
    executor = FakeExecutor([], returncode=17, stderr=b"bounded failure")
    adapter = _adapter(executor)
    request = _isolation_request()

    receipt = adapter.execute(request)
    replay = adapter.execute(request)

    assert receipt is replay
    assert receipt.state is IsolatedProcessState.EXITED
    assert receipt.exit_code == 17
    assert receipt.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert receipt.fallback_performed is False
    assert len(executor.calls) == 1


def test_workspace_process_bridge_returns_content_bound_bounded_result() -> None:
    executor = FakeExecutor([], stdout=b"x" * 10_000, stderr=b"warning")
    isolation = _adapter(executor)
    bridge = PodmanWorkspaceProcessAdapter(
        isolation=isolation,
        mount_resolver=isolation.mount_resolver,
        operation_ledger=_ledger(),
    )
    request = WorkspaceExecRequest(
        operation_id="operation-1",
        binding=_binding(),
        argv=("python", "script.py"),
        cwd="analysis",
        timeout_seconds=30,
        max_output_bytes=512,
        idempotency_key="exec-1",
        authority_lease_id="authority-lease-1",
        authority_generation=2,
        authority_fence=7,
        process_epoch=5,
    )

    receipt = bridge.execute(request)
    payload = json.loads(receipt.result_payload)

    assert receipt.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert len(receipt.result_payload) <= request.max_output_bytes
    assert payload["returncode"] == 0
    assert payload["stdout_truncated"] is True
    assert payload["retry_performed"] is False
    assert payload["fallback_performed"] is False
    assert receipt.digest_payload()["result_payload_digest"] == (
        f"sha256:{hashlib.sha256(receipt.result_payload).hexdigest()}"
    )


def test_workspace_process_bridge_recovers_terminal_receipt_after_host_restart() -> None:
    connection = sqlite3.connect(":memory:")
    first_executor = FakeExecutor([], stdout=b"done")
    first_isolation = _adapter(first_executor)
    request = WorkspaceExecRequest(
        operation_id="operation-restart-1",
        binding=_binding(),
        argv=("python", "script.py"),
        cwd="analysis",
        timeout_seconds=30,
        max_output_bytes=1_024,
        idempotency_key="exec-restart-1",
        authority_lease_id="authority-lease-1",
        authority_generation=2,
        authority_fence=7,
        process_epoch=5,
    )
    first = PodmanWorkspaceProcessAdapter(
        isolation=first_isolation,
        mount_resolver=first_isolation.mount_resolver,
        operation_ledger=_ledger(connection),
    )

    receipt = first.execute(request)

    restarted_executor = FakeExecutor([])
    restarted_isolation = _adapter(restarted_executor)
    restarted = PodmanWorkspaceProcessAdapter(
        isolation=restarted_isolation,
        mount_resolver=restarted_isolation.mount_resolver,
        operation_ledger=_ledger(connection),
    )
    replay = restarted.execute(request)

    assert replay == receipt
    assert len(first_executor.calls) == 1
    assert restarted_executor.calls == []


def test_workspace_process_bridge_preserves_no_effect_failure() -> None:
    isolation = PodmanProcessIsolationAdapter(
        mount_resolver=MappingPodmanWorkspaceMountResolver({}),
        deployment_network="openzyme-deployment",
        executor=FakeExecutor([]),
    )
    bridge = PodmanWorkspaceProcessAdapter(
        isolation=isolation,
        mount_resolver=MappingPodmanWorkspaceMountResolver(
            {"workspace-1": _mount()}
        ),
        operation_ledger=_ledger(),
    )
    request = WorkspaceExecRequest(
        operation_id="operation-1",
        binding=_binding(),
        argv=("python", "script.py"),
        cwd=".",
        timeout_seconds=30,
        max_output_bytes=1_024,
        idempotency_key="exec-1",
        authority_lease_id="authority-lease-1",
        authority_generation=2,
        authority_fence=7,
        process_epoch=5,
    )

    with pytest.raises(WorkspacePortError) as captured:
        bridge.execute(request)

    assert captured.value.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert captured.value.mutation_applied is False


def test_workspace_process_bridge_reconciles_uncertain_receipt_without_retry() -> None:
    executor = FakeExecutor(
        [],
        error=PodmanDispatchError(
            "podman_response_lost",
            "private failure",
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        ),
    )
    isolation = _adapter(executor)
    bridge = PodmanWorkspaceProcessAdapter(
        isolation=isolation,
        mount_resolver=isolation.mount_resolver,
        operation_ledger=_ledger(),
    )
    request = WorkspaceExecRequest(
        operation_id="operation-reconcile-1",
        binding=_binding(),
        argv=("python", "script.py"),
        cwd=".",
        timeout_seconds=30,
        max_output_bytes=1_024,
        idempotency_key="exec-reconcile-1",
        authority_lease_id="authority-lease-1",
        authority_generation=2,
        authority_fence=7,
        process_epoch=5,
    )

    with pytest.raises(WorkspacePortError) as first:
        bridge.execute(request)
    reconciled = bridge.reconcile(request)
    replay = bridge.execute(request)

    assert first.value.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert reconciled.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert replay.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert len(executor.calls) == 1


def test_supervised_executor_bounds_streams_and_settles_timeout() -> None:
    executor = SupervisedSubprocessExecutor(termination_grace_seconds=1)
    bounded = executor.run(
        SupervisedProcessRequest(
            process_identity="process-bounded",
            process_epoch=1,
            authority_fence=1,
            argv=("/bin/sh", "-c", "head -c 4096 /dev/zero"),
            environment={},
            stdin=b"",
            timeout_seconds=2,
            max_output_bytes=256,
        )
    )
    timed_out = executor.run(
        SupervisedProcessRequest(
            process_identity="process-timeout",
            process_epoch=1,
            authority_fence=1,
            argv=("/bin/sh", "-c", "sleep 5"),
            environment={},
            stdin=b"",
            timeout_seconds=1,
            max_output_bytes=256,
        )
    )

    assert len(bounded.stdout) + len(bounded.stderr) <= 256
    assert bounded.stdout_truncated is True
    assert bounded.returncode == 0
    assert timed_out.timed_out is True
    assert timed_out.returncode is not None
