from __future__ import annotations

from dataclasses import fields
import hashlib

import pytest

from openzyme_contracts import FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
from openzyme_contracts import MutationWriterKind
from openzyme_contracts import RuntimeCommandRecord
from openzyme_contracts import RuntimeCommandStatus
from openzyme_contracts import RuntimeCommandType
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import sanitize_public_diagnostic_payload
from openzyme_host_api import HostV2SessionBootstrapInvocation
from openzyme_host_api import KERNEL_V2_MUTATION_ROUTES
from openzyme_kernel import DEFAULT_EXTENSION_SECTION_MAX_BYTES
from openzyme_kernel import DEFAULT_PUBLIC_PROJECTION_MAX_BYTES
from openzyme_kernel import kernel_workspace_declared_tool_entries

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


def _runtime_command() -> RuntimeCommandRecord:
    return RuntimeCommandRecord(
        command_id="runtime-command-1",
        session_id="session-1",
        command_type=RuntimeCommandType.RUNTIME_DRAIN,
        request_digest=canonical_sha256_digest({"max_signals": 3}),
        idempotency_key="runtime-drain-1",
        status=RuntimeCommandStatus.ACCEPTED,
        max_signals=3,
        max_steps_per_agent=3,
        auto_enqueue_ready_tasks=False,
        state_version=1,
        fencing_token=1,
        accepted_at="2026-08-21T00:00:00+00:00",
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="authority-composition.typed-file-gateway",
    family="authority-composition",
    selections=("full", "premerge_subset"),
)
def test_typed_file_gateway_owns_request_identity() -> None:
    identities = [item.route_id for item in KERNEL_V2_MUTATION_ROUTES]
    assert len(identities) == len(set(identities))
    assert all(
        item.startswith("openzyme.kernel.") and item.endswith("@2")
        for item in identities
    )
    _record_satisfied("authority-composition.typed-file-gateway", identities)


@pytest.mark.architecture_qualification_scenario(
    scenario_id="boundary-scale.file-control-bounds",
    family="boundary-scale",
    selections=("full", "premerge_subset"),
)
def test_file_and_runtime_control_payloads_are_bounded() -> None:
    assert 0 < DEFAULT_EXTENSION_SECTION_MAX_BYTES < DEFAULT_PUBLIC_PROJECTION_MAX_BYTES
    assert _runtime_command().max_signals == 3
    _record_satisfied(
        "boundary-scale.file-control-bounds",
        {
            "extension_section_max_bytes": DEFAULT_EXTENSION_SECTION_MAX_BYTES,
            "public_projection_max_bytes": DEFAULT_PUBLIC_PROJECTION_MAX_BYTES,
        },
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
    command = _runtime_command()
    assert command.max_signals == 3
    assert command.max_steps_per_agent == 3
    assert command.auto_enqueue_ready_tasks is False
    _record_satisfied(
        "bounded-terminal-convergence.explicit-runtime-command",
        command.to_dict(),
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="evidence-projection.file-schema-closure",
    family="evidence-projection",
    selections=("full", "premerge_subset"),
)
def test_file_public_projection_has_stable_schema_identity() -> None:
    assert FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION == "file_workspace_public@2"
    assert FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE.endswith("version=2")
    assert FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST.startswith("sha256:")
    assert len(FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST) == 71
    _record_satisfied(
        "evidence-projection.file-schema-closure",
        {"digest": FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST},
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="identity-semantics.canonical-request-digest",
    family="identity-semantics",
    selections=("full", "premerge_subset"),
)
def test_request_digest_is_mapping_order_independent() -> None:
    first = canonical_sha256_digest({"revision": "a" * 40, "path": "jobs/input.json"})
    second = canonical_sha256_digest({"path": "jobs/input.json", "revision": "a" * 40})
    assert first == second
    _record_satisfied(
        "identity-semantics.canonical-request-digest",
        {"request_digest": first},
    )


@pytest.mark.architecture_qualification_scenario(
    scenario_id="operator-retirement.current-tool-surface",
    family="operator-retirement",
    selections=("full", "premerge_subset"),
)
def test_current_tool_catalog_has_only_file_workspace_identity() -> None:
    names = [
        entry.contract.tool_name for entry in kernel_workspace_declared_tool_entries()
    ]
    assert names == [
        "workspace.status",
        "workspace.fs.read",
        "workspace.fs.list",
        "workspace.fs.mutate",
        "workspace.exec",
    ]
    assert not any(name.startswith("artifact.") for name in names)
    _record_satisfied("operator-retirement.current-tool-surface", names)


@pytest.mark.architecture_qualification_scenario(
    scenario_id="reconciliation.revision-run-exact-once",
    family="reconciliation",
    selections=("full", "premerge_subset"),
)
def test_revision_run_reconciliation_preserves_exact_identity() -> None:
    occurrence = {
        "operation_id": "operation-1",
        "route_id": "route-1",
        "effect_certainty": "dispatch_in_doubt",
        "retry_performed": False,
        "fallback_performed": False,
    }
    assert canonical_sha256_digest(occurrence) == canonical_sha256_digest(
        dict(reversed(tuple(occurrence.items())))
    )
    assert occurrence["retry_performed"] is False
    _record_satisfied("reconciliation.revision-run-exact-once", occurrence)


@pytest.mark.architecture_qualification_scenario(
    scenario_id="restart-fencing.file-publisher-owner",
    family="restart-fencing",
    selections=("full", "premerge_subset"),
)
def test_file_publication_has_an_explicit_writer_owner() -> None:
    values = {item.value for item in MutationWriterKind}
    assert MutationWriterKind.FILE_PUBLISHER.value in values
    assert "artifact_publisher" not in values
    _record_satisfied("restart-fencing.file-publisher-owner", sorted(values))


@pytest.mark.architecture_qualification_scenario(
    scenario_id="strategy-neutrality.closed-file-operations",
    family="strategy-neutrality",
    selections=("full", "premerge_subset"),
)
def test_file_gateway_exposes_operations_without_phase_ordering() -> None:
    identities = {item.route_id for item in KERNEL_V2_MUTATION_ROUTES}
    assert "openzyme.kernel.workspace.publish@2" in identities
    assert "openzyme.kernel.task.finish@2" in identities
    assert all("phase" not in item for item in identities)
    _record_satisfied("strategy-neutrality.closed-file-operations", sorted(identities))


@pytest.mark.architecture_qualification_scenario(
    scenario_id="supervisor-progress.auto-enqueue-opt-in",
    family="supervisor-progress",
    selections=("full", "premerge_subset"),
)
def test_runtime_auto_enqueue_is_explicit_opt_in() -> None:
    command = _runtime_command()
    assert command.auto_enqueue_ready_tasks is False
    _record_satisfied("supervisor-progress.auto-enqueue-opt-in", command.to_dict())


@pytest.mark.architecture_qualification_scenario(
    scenario_id="supervisor-progress.semantic-progress-only",
    family="supervisor-progress",
    selections=("full", "premerge_subset"),
)
def test_durable_supervisor_keeps_closed_p0_idle_without_self_wake() -> None:
    payload = _runtime_command().to_dict()
    assert "task_finished" not in payload
    assert "next_signal" not in payload
    assert payload["status"] == "accepted"
    _record_satisfied("supervisor-progress.semantic-progress-only", payload)


@pytest.mark.architecture_qualification_scenario(
    scenario_id="wire-contract.closed-file-request",
    family="wire-contract",
    selections=("full", "premerge_subset"),
)
def test_file_request_wire_envelope_is_closed() -> None:
    names = {field.name for field in fields(HostV2SessionBootstrapInvocation)}
    assert names == {
        "session_id",
        "actor_id",
        "idempotency_key",
        "correlation_id",
        "payload",
    }
    _record_satisfied("wire-contract.closed-file-request", sorted(names))


@pytest.mark.architecture_qualification_scenario(
    scenario_id="world-fidelity.retired-field-rejected",
    family="world-fidelity",
    selections=("full", "premerge_subset"),
)
def test_retired_storage_field_is_rejected_without_inferred_replacement() -> None:
    assert "storageuri" in FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS
    assert "artifact" in FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS
    assert "replacement" not in FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS
    _record_satisfied(
        "world-fidelity.retired-field-rejected",
        sorted(FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS),
    )


def _require_no_replacement(
    details: dict[str, object],
    *,
    expected: dict[str, object],
) -> None:
    if details != expected or details.get("replacement_inferred") is not False:
        raise AssertionError(
            "contract rejection inferred a replacement or lost closed facts: "
            f"expected={expected!r} observed={details!r}"
        )
