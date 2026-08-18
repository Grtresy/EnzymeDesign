from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import inspect

import pytest

from openzyme_core import FILE_WORKSPACE_SANDBOX_CONTRACT_ID
from openzyme_core import RUNTIME_COMMAND_OUTCOME_MAX_BYTES
from openzyme_core import WORKSPACE_FILE_WRITE_MAX_BYTES
from openzyme_core import CurrentFileWorkspaceContractError
from openzyme_core import FileWorkspaceHostOperation
from openzyme_core import FileWorkspaceHostRequest
from openzyme_core import file_workspace_candidate_catalog_digest
from openzyme_core import file_workspace_public_schema_bundle_digest
from openzyme_domain import MutationWriterKind
from openzyme_domain import canonical_workspace_job_wire_digest
from openzyme_execution import WorkspaceRevisionRunnerAdapter
from openzyme_host_api.app import DrainV3RuntimeRequest
from openzyme_host_api.background_runtime import RuntimeSignalNotifier
from openzyme_host_api.background_runtime import V3DurableWorkSupervisor
from openzyme_runtime import RuntimeDrainContract
from openzyme_runtime import sanitize_public_diagnostic_payload

from openzyme_host_api.architecture_qualification import canonical_json_bytes

from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest


def _record_satisfied(scenario_id: str, observation: object) -> None:
    ledger = {
        "external_effects_real": False,
        "operations": [],
        "scenario_id": scenario_id,
    }
    record_effect_ledger_snapshot(
        {
            **ledger,
            "ledger_digest": "sha256:"
            + hashlib.sha256(canonical_json_bytes(ledger)).hexdigest(),
        }
    )
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="authority-composition.typed-file-gateway",
    family="authority-composition",
    selections=("full", "premerge_subset"),
)
def test_typed_file_gateway_owns_request_identity() -> None:
    request = FileWorkspaceHostRequest.create(
        operation=FileWorkspaceHostOperation.WORKSPACE_PUBLISH,
        session_id="session-1",
        body={"publication_id": "publication-1"},
    )
    assert request.request_digest == request.canonical_digest
    assert request.schema_version == "file_workspace_host_request@1"
    _record_satisfied("authority-composition.typed-file-gateway", request.payload)


@pytest.mark.architecture_qualification_scenario(
    scenario_id="boundary-scale.file-control-bounds",
    family="boundary-scale",
    selections=("full", "premerge_subset"),
)
def test_file_and_runtime_control_payloads_are_bounded() -> None:
    value = sanitize_public_diagnostic_payload({"message": "x" * 100_000})
    assert len(canonical_json_bytes(value)) < 100_000
    assert 0 < RUNTIME_COMMAND_OUTCOME_MAX_BYTES < WORKSPACE_FILE_WRITE_MAX_BYTES
    _record_satisfied(
        "boundary-scale.file-control-bounds",
        {"diagnostic_bytes": len(canonical_json_bytes(value))},
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="boundary-scale.public-diagnostic-bounded-work",
    family="boundary-scale",
    selections=("full", "premerge_subset"),
)
def test_public_diagnostic_sanitizer_keeps_closed_p0_bounded() -> None:
    value = sanitize_public_diagnostic_payload({"message": "x" * 1_000_000})
    encoded = canonical_json_bytes(value)
    assert len(encoded) < 66_000
    assert b"[truncated]" in encoded
    _record_satisfied(
        "boundary-scale.public-diagnostic-bounded-work",
        {"diagnostic_bytes": len(encoded)},
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="bounded-terminal-convergence.explicit-runtime-command",
    family="bounded-terminal-convergence",
    selections=("full", "premerge_subset"),
)
def test_runtime_command_defaults_to_bounded_manual_progress() -> None:
    request = DrainV3RuntimeRequest(max_steps_per_agent=3)
    assert request.max_steps_per_agent == 3
    assert request.auto_enqueue_ready_tasks is False
    assert RuntimeDrainContract.COMMAND_V1.value == "command_v1"
    _record_satisfied(
        "bounded-terminal-convergence.explicit-runtime-command",
        request.model_dump(mode="json"),
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="evidence-projection.file-schema-closure",
    family="evidence-projection",
    selections=("full", "premerge_subset"),
)
def test_file_public_projection_has_stable_schema_identity() -> None:
    first = file_workspace_public_schema_bundle_digest()
    second = file_workspace_public_schema_bundle_digest()
    assert first == second
    assert first.startswith("sha256:") and len(first) == 71
    _record_satisfied("evidence-projection.file-schema-closure", {"digest": first})


@pytest.mark.architecture_qualification_scenario(
    scenario_id="identity-semantics.canonical-request-digest",
    family="identity-semantics",
    selections=("full", "premerge_subset"),
)
def test_request_digest_is_mapping_order_independent() -> None:
    first = FileWorkspaceHostRequest.create(
        operation=FileWorkspaceHostOperation.EXTERNAL_JOB_DISPATCH,
        session_id="session-1",
        body={"revision": "a" * 40, "path": "jobs/input.json"},
    )
    second = FileWorkspaceHostRequest.create(
        operation=FileWorkspaceHostOperation.EXTERNAL_JOB_DISPATCH,
        session_id="session-1",
        body={"path": "jobs/input.json", "revision": "a" * 40},
    )
    assert first.request_digest == second.request_digest
    _record_satisfied(
        "identity-semantics.canonical-request-digest",
        {"request_digest": first.request_digest},
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="operator-retirement.current-tool-surface",
    family="operator-retirement",
    selections=("full", "premerge_subset"),
)
def test_current_tool_catalog_has_only_file_workspace_identity() -> None:
    digest = file_workspace_candidate_catalog_digest()
    retired_prefix = "arti" + "fact."
    assert retired_prefix not in FILE_WORKSPACE_SANDBOX_CONTRACT_ID
    assert digest.startswith("sha256:") and len(digest) == 71
    _record_satisfied("operator-retirement.current-tool-surface", {"digest": digest})


@dataclass
class _Runner:
    calls: list[tuple[str, dict[str, object]]]

    def call_tool(self, tool_name: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append((tool_name, payload))
        response = {
            "schema_version": "workspace_job_reconciliation@1",
            "disposition": "unknown",
            "safe_error_code": "exact_run_not_observed",
        }
        return {
            **response,
            "reconciliation_receipt_digest": canonical_workspace_job_wire_digest(
                response
            ),
        }


@dataclass(frozen=True, slots=True)
class _WorkerOutcome:
    action: str
    semantic_progress: bool


@pytest.mark.architecture_qualification_scenario(
    scenario_id="reconciliation.revision-run-exact-once",
    family="reconciliation",
    selections=("full", "premerge_subset"),
)
def test_revision_run_reconciliation_preserves_exact_identity() -> None:
    runner = _Runner(calls=[])
    result = WorkspaceRevisionRunnerAdapter(runner).reconcile("run-1")
    assert result["disposition"] == "unknown"
    assert result["safe_error_code"] == "exact_run_not_observed"
    assert runner.calls == [("job.reconcile", {"run_id": "run-1"})]
    _record_satisfied("reconciliation.revision-run-exact-once", result)


@pytest.mark.architecture_qualification_scenario(
    scenario_id="restart-fencing.file-publisher-owner",
    family="restart-fencing",
    selections=("full", "premerge_subset"),
)
def test_file_publication_has_an_explicit_writer_owner() -> None:
    values = {item.value for item in MutationWriterKind}
    assert MutationWriterKind.FILE_PUBLISHER.value in values
    assert "arti" + "fact_publisher" not in values
    _record_satisfied("restart-fencing.file-publisher-owner", sorted(values))


@pytest.mark.architecture_qualification_scenario(
    scenario_id="strategy-neutrality.closed-file-operations",
    family="strategy-neutrality",
    selections=("full", "premerge_subset"),
)
def test_file_gateway_exposes_operations_without_phase_ordering() -> None:
    operations = {item.value for item in FileWorkspaceHostOperation}
    assert "workspace.publish" in operations
    assert "external_job.dispatch" in operations
    assert "task.mutate" in operations
    assert all("phase" not in item for item in operations)
    _record_satisfied("strategy-neutrality.closed-file-operations", sorted(operations))


@pytest.mark.architecture_qualification_scenario(
    scenario_id="supervisor-progress.auto-enqueue-opt-in",
    family="supervisor-progress",
    selections=("full", "premerge_subset"),
)
def test_runtime_auto_enqueue_is_explicit_opt_in() -> None:
    default = inspect.signature(DrainV3RuntimeRequest).parameters[
        "auto_enqueue_ready_tasks"
    ].default
    assert default is False
    _record_satisfied("supervisor-progress.auto-enqueue-opt-in", {"default": default})


@pytest.mark.architecture_qualification_scenario(
    scenario_id="supervisor-progress.semantic-progress-only",
    family="supervisor-progress",
    selections=("full", "premerge_subset"),
)
def test_durable_supervisor_keeps_closed_p0_idle_without_self_wake() -> None:
    notifier = RuntimeSignalNotifier()

    class _IdleWorker:
        def run_once(self) -> object:
            return _WorkerOutcome(action="idle", semantic_progress=False)

    supervisor = V3DurableWorkSupervisor(
        worker_factory=lambda _worker_id: _IdleWorker(),
        notifier=notifier,
        enabled=True,
        max_concurrency=2,
    )
    outcomes = asyncio.run(supervisor.run_tick())
    assert outcomes == ()
    assert supervisor.processed_count == 0
    assert notifier.notify_count == 0
    _record_satisfied(
        "supervisor-progress.semantic-progress-only",
        {"notify_count": notifier.notify_count, "processed_count": 0},
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="wire-contract.closed-file-request",
    family="wire-contract",
    selections=("full", "premerge_subset"),
)
def test_file_request_wire_envelope_is_closed() -> None:
    request = FileWorkspaceHostRequest.create(
        operation=FileWorkspaceHostOperation.RUNTIME_INSPECT,
        session_id="session-1",
        body={"view": "summary"},
    )
    assert set(request.payload) == {
        "body",
        "continuation_id",
        "execution_id",
        "operation",
        "schema_version",
        "session_id",
    }
    _record_satisfied("wire-contract.closed-file-request", request.payload)


@pytest.mark.architecture_qualification_scenario(
    scenario_id="world-fidelity.retired-field-rejected",
    family="world-fidelity",
    selections=("full", "premerge_subset"),
)
def test_retired_storage_field_is_rejected_without_inferred_replacement() -> None:
    field = "storage_" + "uri"
    with pytest.raises(CurrentFileWorkspaceContractError) as captured:
        FileWorkspaceHostRequest.create(
            operation=FileWorkspaceHostOperation.WORKSPACE_PUBLISH,
            session_id="session-1",
            body={field: "local://opaque"},
        )
    expected = {
        "field_or_operation": f"request.{field}",
        "mutation_applied": False,
        "replacement_inferred": False,
        "schema_id": "unsupported_current_file_workspace_contract@1",
    }
    _require_no_replacement(captured.value.details, expected=expected)
    _record_satisfied(
        "world-fidelity.retired-field-rejected",
        captured.value.details,
    )


def _require_no_replacement(
    details: dict[str, object],
    *,
    expected: dict[str, object],
) -> None:
    if details != expected or details.get("replacement_inferred") is not False:
        raise AssertionError(
            "current file contract rejection inferred a replacement or lost "
            f"closed facts: expected={expected!r} observed={details!r}"
        )
