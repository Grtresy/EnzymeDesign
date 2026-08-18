from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_hpc_runner import models
from mcp_hpc_runner.models import ExecutorWorkspaceRunSpec
from mcp_hpc_runner.models import ResourceSpec
from mcp_hpc_runner.models import WorkspaceSourceManifestEntry
from mcp_hpc_runner.workspace_revision_jobs import WorkspaceRevisionJobInDoubt
from mcp_hpc_runner.workspace_revision_jobs import SchedulerOccurrenceCredential
from mcp_hpc_runner.workspace_revision_jobs import WorkspaceRevisionJobError
from mcp_hpc_runner.workspace_revision_jobs import WorkspaceRevisionJobService
from mcp_hpc_runner.transport import SshTransportError
from openzyme_domain import WorkspaceJobWireContractError
from openzyme_domain import canonical_workspace_job_wire_digest
from openzyme_domain import serialize_workspace_job_cancellation_receipt


DIGEST = f"sha256:{'a' * 64}"
NOW = "2026-08-18T00:00:00+00:00"


class _NoTransport:
    calls = 0

    def run_ssh(self, *_: object, **__: object) -> object:
        self.calls += 1
        raise AssertionError("backend transport must not run during replay validation")


def _runspec() -> ExecutorWorkspaceRunSpec:
    entry = WorkspaceSourceManifestEntry(
        path="src/main.py",
        object_id="3" * 40,
        mode="100644",
        size_bytes=12,
        content_digest=DIGEST,
    )
    resources = ResourceSpec()
    manifest_payload = {
        "schema_version": "compute_source_manifest@1",
        "manifest_id": "manifest_1",
        "request_id": "source_request_1",
        "workspace_id": "workspace_1",
        "source_commit": "1" * 40,
        "source_tree": "2" * 40,
        "lfs_closure_manifest_digest": DIGEST,
        "binding_digest": DIGEST,
        "repository_policy_digest": DIGEST,
        "toolchain_digest": DIGEST,
        "owner_identity_digest": DIGEST,
        "entries": [entry.to_dict()],
        "created_at": NOW,
    }
    return ExecutorWorkspaceRunSpec(
        execution_id="execution_1",
        operation_id="operation_1",
        dispatch_id="dispatch_1",
        runner_run_id="run_1",
        executor_hpc_workspace_id="workspace_1",
        executor_hpc_workspace_generation=1,
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_binding_digest=DIGEST,
        repository_policy_digest=DIGEST,
        source_manifest_id="manifest_1",
        source_request_id="source_request_1",
        source_commit="1" * 40,
        source_tree="2" * 40,
        lfs_closure_manifest_digest=DIGEST,
        source_manifest=(entry,),
        source_manifest_digest=models._canonical_digest(manifest_payload),
        source_owner_identity_digest=DIGEST,
        source_manifest_created_at=NOW,
        target_profile_digest=DIGEST,
        runner_policy_digest=DIGEST,
        toolchain_digest=DIGEST,
        cwd=".",
        command=("true",),
        command_digest=models._canonical_digest(["true"]),
        environment_policy_digest=DIGEST,
        resource_digest=models._canonical_digest(resources.to_dict()),
        selected_mode="ssh",
        scheduler_marker="marker_1",
        payload_digest=DIGEST,
        absolute_deadline="2027-08-18T00:00:00+00:00",
        resources=resources,
    )


def _handle(spec: ExecutorWorkspaceRunSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "workspace_job_runner_handle@1",
        "disposition": "accepted",
        "handle_id": "handle_1",
        "execution_id": spec.execution_id,
        "operation_id": spec.operation_id,
        "dispatch_id": spec.dispatch_id,
        "runner_run_id": spec.runner_run_id,
        "job_root_token": "job_root_1",
        "target_profile_digest": spec.target_profile_digest,
        "workspace_id": spec.executor_hpc_workspace_id,
        "remote_workspace_generation": spec.executor_hpc_workspace_generation,
        "source_commit": spec.source_commit,
        "source_manifest_digest": spec.source_manifest_digest,
        "backend": "slurm" if spec.selected_mode == "sbatch" else "direct",
        "raw_handle_ciphertext": "private-ciphertext",
        "acceptance_receipt_digest": DIGEST,
        "accepted_at": NOW,
        "credential_consumed_at": NOW if spec.selected_mode == "sbatch" else None,
        "credential_consumption_receipt_digest": (
            DIGEST if spec.selected_mode == "sbatch" else None
        ),
    }
    return {**payload, "handle_digest": canonical_workspace_job_wire_digest(payload)}


def _cancellation() -> dict[str, Any]:
    return {
        "schema_version": "workspace_job_cancellation_intent@1",
        "cancellation_id": "cancel_1",
        "execution_id": "execution_1",
        "handle_id": "handle_1",
        "execution_state_version": 3,
        "execution_fencing_token": 7,
        "idempotency_key": "cancel-key-1",
        "reason_digest": DIGEST,
        "created_at": NOW,
    }


def _observation(
    spec: ExecutorWorkspaceRunSpec,
    *,
    index: int = 1,
    state: str = "running",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "external_job_observation@1",
        "observation_id": f"job_observation_handle_1_{index}",
        "handle_id": "handle_1",
        "execution_id": spec.execution_id,
        "dispatch_id": spec.dispatch_id,
        "observation_index": index,
        "state": state,
        "exit_code": 0 if state == "succeeded" else None,
        "terminal_receipt_digest": (
            DIGEST if state in {"succeeded", "failed", "cancelled"} else None
        ),
        "bounded_stdout": "still running",
        "bounded_stderr": None,
        "observed_at": NOW,
    }
    return {
        **payload,
        "observation_digest": canonical_workspace_job_wire_digest(payload),
    }


def _service(tmp_path: Path) -> tuple[WorkspaceRevisionJobService, _NoTransport]:
    transport = _NoTransport()
    service = WorkspaceRevisionJobService(
        SimpleNamespace(
            control_root=tmp_path,
            execution=SimpleNamespace(remote_execution_timeout_seconds=30),
        ),  # type: ignore[arg-type]
        transport,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )
    service._require_before_deadline = lambda _: None  # type: ignore[method-assign]
    service._qualification = lambda **_: SimpleNamespace(  # type: ignore[method-assign]
        protected_wrapper_path="/qualified/openzyme-wrapper",
        scheduler_credential_audience="openzyme-wrapper",
        slurm_enabled=True,
        direct_enabled=True,
    )
    service._private_workspace = lambda **_: {  # type: ignore[method-assign]
        "workspace_id": "workspace_1",
        "private_path": "/qualified/private/workspace",
    }
    return service, transport


def _scheduler_credential(spec: ExecutorWorkspaceRunSpec) -> SchedulerOccurrenceCredential:
    return SchedulerOccurrenceCredential(
        occurrence_id="occurrence_1",
        dispatch_id=spec.dispatch_id,
        execution_id=spec.execution_id,
        target_profile_digest=spec.target_profile_digest,
        reservation_nonce_digest=DIGEST,
        scheduler_marker=spec.scheduler_marker,
        payload_digest=spec.payload_digest,
        protected_wrapper_audience="openzyme-wrapper",
        expires_at="2027-08-18T00:00:00+00:00",
        opaque_token="opaque-one-occurrence-token",
    )


def _seed_dispatch(service: WorkspaceRevisionJobService, spec: ExecutorWorkspaceRunSpec) -> None:
    service._write_once(service._record_path("runspecs", spec.runner_run_id), spec.to_dict())
    service._write_once(
        service._record_path("dispatch-intents", spec.dispatch_id),
        service._dispatch_identity(spec),
    )
    service._write_once(
        service._record_path("handles", spec.dispatch_id),
        _handle(spec),
    )


def test_dispatch_replay_revalidates_handle_without_transport(tmp_path: Path) -> None:
    service, transport = _service(tmp_path)
    spec = _runspec()
    _seed_dispatch(service, spec)

    assert service.dispatch(spec)["handle_id"] == "handle_1"
    assert transport.calls == 0


def test_tampered_replay_handle_fails_before_transport(tmp_path: Path) -> None:
    service, transport = _service(tmp_path)
    spec = _runspec()
    _seed_dispatch(service, spec)
    tampered = _handle(spec)
    tampered["source_commit"] = "4" * 40
    tampered["handle_digest"] = canonical_workspace_job_wire_digest(
        {key: value for key, value in tampered.items() if key != "handle_digest"}
    )
    path = service._record_path("handles", spec.dispatch_id)
    path.unlink()
    service._write_once(path, tampered)

    with pytest.raises(WorkspaceJobWireContractError) as captured:
        service.dispatch(spec)

    assert captured.value.error_code == "workspace_job_wire_identity_mismatch"
    assert captured.value.field == "source_commit"
    assert transport.calls == 0


def test_reconcile_restart_replays_validated_handle_without_backend_action(
    tmp_path: Path,
) -> None:
    service, transport = _service(tmp_path)
    spec = _runspec()
    _seed_dispatch(service, spec)
    wrapper_calls = 0

    def invoke(*_: object, **__: object) -> dict[str, Any]:
        nonlocal wrapper_calls
        wrapper_calls += 1
        raise AssertionError("reconcile backend must not run for a durable handle")

    service._invoke_wrapper = invoke  # type: ignore[method-assign]

    assert service.reconcile(spec) == _handle(spec)
    assert wrapper_calls == 0
    assert transport.calls == 0


def test_observe_restart_replays_validated_observation_without_backend_action(
    tmp_path: Path,
) -> None:
    service, transport = _service(tmp_path)
    spec = _runspec()
    _seed_dispatch(service, spec)
    observation = _observation(spec)
    service._write_once(
        service._record_path("observations", f"{spec.dispatch_id}-1"),
        observation,
    )
    wrapper_calls = 0

    def invoke(*_: object, **__: object) -> dict[str, Any]:
        nonlocal wrapper_calls
        wrapper_calls += 1
        raise AssertionError("observe backend must not run for a durable observation")

    service._invoke_wrapper = invoke  # type: ignore[method-assign]

    assert service.observe(spec, index=1) == observation
    assert wrapper_calls == 0
    assert transport.calls == 0


def test_tampered_observation_replay_fails_before_backend_action(tmp_path: Path) -> None:
    service, transport = _service(tmp_path)
    spec = _runspec()
    _seed_dispatch(service, spec)
    observation = _observation(spec)
    observation["dispatch_id"] = "dispatch_other"
    observation["observation_digest"] = canonical_workspace_job_wire_digest(
        {
            key: value
            for key, value in observation.items()
            if key != "observation_digest"
        }
    )
    service._write_once(
        service._record_path("observations", f"{spec.dispatch_id}-1"),
        observation,
    )
    wrapper_calls = 0

    def invoke(*_: object, **__: object) -> dict[str, Any]:
        nonlocal wrapper_calls
        wrapper_calls += 1
        raise AssertionError("backend must not run after replay identity drift")

    service._invoke_wrapper = invoke  # type: ignore[method-assign]

    with pytest.raises(WorkspaceJobWireContractError) as captured:
        service.observe(spec, index=1)

    assert captured.value.error_code == "workspace_job_wire_identity_mismatch"
    assert captured.value.field == "dispatch_id"
    assert wrapper_calls == 0
    assert transport.calls == 0


def test_cancellation_receipt_round_trip_and_replay_are_single_effect(
    tmp_path: Path,
) -> None:
    service, transport = _service(tmp_path)
    spec = _runspec()
    _seed_dispatch(service, spec)
    wrapper_calls: list[str] = []

    def invoke(*_: object, **__: object) -> dict[str, Any]:
        wrapper_calls.append("cancel")
        return serialize_workspace_job_cancellation_receipt(
            receipt_id="cancel_receipt_1",
            cancellation_id="cancel_1",
            handle_id="handle_1",
            backend_receipt_digest=DIGEST,
            created_at=NOW,
        )

    service._invoke_wrapper = invoke  # type: ignore[method-assign]

    first = service.cancel(spec, cancellation=_cancellation())
    second = service.cancel(spec, cancellation=_cancellation())

    assert first == second
    assert first["receipt_id"] == "cancel_receipt_1"
    assert wrapper_calls == ["cancel"]
    assert transport.calls == 0


def test_missing_receipt_id_leaves_in_doubt_intent_and_never_recancels(
    tmp_path: Path,
) -> None:
    service, _transport = _service(tmp_path)
    spec = _runspec()
    _seed_dispatch(service, spec)
    valid = serialize_workspace_job_cancellation_receipt(
        receipt_id="cancel_receipt_1",
        cancellation_id="cancel_1",
        handle_id="handle_1",
        backend_receipt_digest=DIGEST,
        created_at=NOW,
    )
    invalid = deepcopy(valid)
    invalid.pop("receipt_id")
    wrapper_calls = 0

    def invoke(*_: object, **__: object) -> dict[str, Any]:
        nonlocal wrapper_calls
        wrapper_calls += 1
        return invalid

    service._invoke_wrapper = invoke  # type: ignore[method-assign]

    with pytest.raises(WorkspaceJobWireContractError) as first_error:
        service.cancel(spec, cancellation=_cancellation())
    assert first_error.value.error_code == "workspace_job_wire_fields_mismatch"

    with pytest.raises(WorkspaceRevisionJobInDoubt):
        service.cancel(spec, cancellation=_cancellation())
    assert wrapper_calls == 1


@pytest.mark.parametrize("selected_mode", ["ssh", "sbatch"])
def test_direct_and_slurm_lifecycle_requires_terminal_observation(
    tmp_path: Path,
    selected_mode: str,
) -> None:
    service, transport = _service(tmp_path)
    spec = replace(_runspec(), selected_mode=selected_mode)
    backend_actions: list[str] = []

    def dispatch(*_: object, **__: object) -> object:
        backend_actions.append("dispatch")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_handle(spec)),
            stderr="",
            timed_out=False,
            process_started=True,
        )

    transport.run_ssh = dispatch  # type: ignore[method-assign]
    wrapper_actions: list[str] = []

    def invoke(
        _qualification: object,
        action: str,
        body: dict[str, object],
        **_: object,
    ) -> dict[str, Any]:
        wrapper_actions.append(action)
        if action == "observe":
            index = int(body["observation_index"])
            return _observation(
                spec,
                index=index,
                state="running" if index == 1 else "cancelled",
            )
        if action == "cancel":
            return serialize_workspace_job_cancellation_receipt(
                receipt_id="cancel_receipt_1",
                cancellation_id="cancel_1",
                handle_id="handle_1",
                backend_receipt_digest=DIGEST,
                created_at=NOW,
            )
        raise AssertionError(f"unexpected wrapper action: {action}")

    service._invoke_wrapper = invoke  # type: ignore[method-assign]

    handle = service.dispatch(
        spec,
        scheduler_credential=(
            _scheduler_credential(spec) if selected_mode == "sbatch" else None
        ),
    )
    running = service.observe(spec, index=1)
    cancellation = service.cancel(spec, cancellation=_cancellation())
    cancelled = service.observe(spec, index=2)
    reconciled = service.reconcile(spec)

    assert handle["backend"] == ("slurm" if selected_mode == "sbatch" else "direct")
    assert running["state"] == "running"
    assert running["terminal_receipt_digest"] is None
    assert cancellation["cancellation_requested"] is True
    assert cancellation["terminal_settlement_proven"] is False
    assert cancelled["state"] == "cancelled"
    assert cancelled["terminal_receipt_digest"] == DIGEST
    assert reconciled == handle
    assert backend_actions == ["dispatch"]
    assert wrapper_actions == ["observe", "cancel", "observe"]


def test_dispatch_response_loss_requires_reconcile_and_never_resubmits(
    tmp_path: Path,
) -> None:
    service, transport = _service(tmp_path)
    spec = _runspec()
    dispatch_calls = 0

    def lose_response(*_: object, **__: object) -> object:
        nonlocal dispatch_calls
        dispatch_calls += 1
        raise SshTransportError("ssh_response_lost", "dispatch response was lost")

    transport.run_ssh = lose_response  # type: ignore[method-assign]

    with pytest.raises(WorkspaceRevisionJobInDoubt) as first:
        service.dispatch(spec)

    restarted, restarted_transport = _service(tmp_path)
    restarted_transport.run_ssh = lose_response  # type: ignore[method-assign]
    with pytest.raises(WorkspaceRevisionJobInDoubt, match="must be reconciled"):
        restarted.dispatch(spec)

    assert first.value.__cause__ is not None
    assert dispatch_calls == 1

    restarted._invoke_wrapper = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: _handle(spec)
    )
    assert restarted.reconcile(spec) == _handle(spec)
    assert restarted.dispatch(spec) == _handle(spec)
    assert dispatch_calls == 1


def test_missing_handle_blocks_observe_and_cancel_before_backend_action(
    tmp_path: Path,
) -> None:
    service, transport = _service(tmp_path)
    spec = _runspec()
    service._write_once(
        service._record_path("runspecs", spec.runner_run_id),
        spec.to_dict(),
    )
    service._write_once(
        service._record_path("dispatch-intents", spec.dispatch_id),
        service._dispatch_identity(spec),
    )
    wrapper_calls = 0

    def invoke(*_: object, **__: object) -> dict[str, Any]:
        nonlocal wrapper_calls
        wrapper_calls += 1
        raise AssertionError("missing handle must fail before backend action")

    service._invoke_wrapper = invoke  # type: ignore[method-assign]

    with pytest.raises(WorkspaceRevisionJobError, match="handle is not durable"):
        service.observe(spec, index=1)
    with pytest.raises(WorkspaceRevisionJobError, match="handle is not durable"):
        service.cancel(spec, cancellation=_cancellation())

    assert wrapper_calls == 0
    assert transport.calls == 0


def test_tampered_dispatch_journal_blocks_replay_before_backend_action(
    tmp_path: Path,
) -> None:
    service, transport = _service(tmp_path)
    spec = _runspec()
    tampered_intent = service._dispatch_identity(spec)
    tampered_intent["source_commit"] = "4" * 40
    service._write_once(
        service._record_path("dispatch-intents", spec.dispatch_id),
        tampered_intent,
    )

    with pytest.raises(WorkspaceRevisionJobError, match="conflicts with its frozen intent"):
        service.dispatch(spec)

    assert transport.calls == 0
    assert not service._record_path("handles", spec.dispatch_id).exists()


def test_slurm_response_loss_never_reuses_one_occurrence_credential(
    tmp_path: Path,
) -> None:
    service, transport = _service(tmp_path)
    spec = replace(_runspec(), selected_mode="sbatch")
    credential = _scheduler_credential(spec)
    dispatch_calls = 0

    def lose_response(*_: object, **__: object) -> object:
        nonlocal dispatch_calls
        dispatch_calls += 1
        raise SshTransportError("ssh_response_lost", "dispatch response was lost")

    transport.run_ssh = lose_response  # type: ignore[method-assign]
    with pytest.raises(WorkspaceRevisionJobInDoubt):
        service.dispatch(spec, scheduler_credential=credential)

    restarted, restarted_transport = _service(tmp_path)
    restarted_transport.run_ssh = lose_response  # type: ignore[method-assign]
    with pytest.raises(WorkspaceRevisionJobInDoubt, match="must be reconciled"):
        restarted.dispatch(spec, scheduler_credential=credential)

    assert dispatch_calls == 1


def test_scheduler_credential_identity_drift_fails_before_intent_or_backend(
    tmp_path: Path,
) -> None:
    service, transport = _service(tmp_path)
    spec = replace(_runspec(), selected_mode="sbatch")
    credential = replace(_scheduler_credential(spec), execution_id="execution_other")

    with pytest.raises(WorkspaceRevisionJobError, match="identity drifted"):
        service.dispatch(spec, scheduler_credential=credential)

    assert transport.calls == 0
    assert not service._record_path("dispatch-intents", spec.dispatch_id).exists()


def test_cancel_response_loss_survives_restart_without_replacement_cancel(
    tmp_path: Path,
) -> None:
    service, _transport = _service(tmp_path)
    spec = _runspec()
    _seed_dispatch(service, spec)
    cancel_calls = 0

    def lose_cancel(
        _qualification: object,
        action: str,
        _body: dict[str, object],
        **_: object,
    ) -> dict[str, Any]:
        nonlocal cancel_calls
        assert action == "cancel"
        cancel_calls += 1
        raise SshTransportError("ssh_response_lost", "cancel response was lost")

    service._invoke_wrapper = lose_cancel  # type: ignore[method-assign]
    with pytest.raises(SshTransportError):
        service.cancel(spec, cancellation=_cancellation())

    restarted, _ = _service(tmp_path)
    restarted._invoke_wrapper = lose_cancel  # type: ignore[method-assign]
    with pytest.raises(WorkspaceRevisionJobInDoubt, match="same handle"):
        restarted.cancel(spec, cancellation=_cancellation())

    assert cancel_calls == 1


def test_dispatch_rejects_expired_deadline_before_backend_or_intent(
    tmp_path: Path,
) -> None:
    service, transport = _service(tmp_path)
    service._require_before_deadline = (  # type: ignore[method-assign]
        WorkspaceRevisionJobService._require_before_deadline
    )
    spec = replace(_runspec(), absolute_deadline="2020-01-01T00:00:00+00:00")

    with pytest.raises(WorkspaceRevisionJobError, match="deadline"):
        service.dispatch(spec)

    assert transport.calls == 0
    assert not service._record_path("dispatch-intents", spec.dispatch_id).exists()


def test_runner_source_imports_only_the_dependency_free_domain_contract() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "mcp_hpc_runner"
    forbidden_roots = {
        "openzyme_core",
        "openzyme_engines",
        "openzyme_execution",
        "openzyme_runtime",
    }
    violations: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {item.name.split(".", 1)[0] for item in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported = {node.module.split(".", 1)[0]}
            else:
                continue
            for forbidden in sorted(imported & forbidden_roots):
                violations.append(f"{path.relative_to(source_root)}:{node.lineno}:{forbidden}")

    assert violations == []
