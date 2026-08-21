from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ToolResult
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import ControlledOperationApplicationCommand
from openzyme_extension_spi import ControlledOperationCommandKind
from openzyme_extension_spi import ExtensionMutationPlan
from openzyme_extension_spi import ExtensionMutationResult
from openzyme_extension_spi import ExtensionStateCommand
from openzyme_extension_spi import ExtensionStateMutation
from openzyme_extension_spi import ExtensionStateMutationKind
from openzyme_extension_spi import ExtensionTransactionBudget
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import ProjectionResult
from openzyme_extension_spi import SubordinateDriver


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _context(*, route_id: str | None = "hpc:primary/hmmer") -> KernelCommandContext:
    return KernelCommandContext(
        command_id="command-1",
        session_id="session-1",
        actor_id="member-1",
        owner_plugin_id="enzymedesign.hmmer",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=7,
        expected_session_version=11,
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("binding"),
        idempotency_key="search-1",
        correlation_id="correlation-1",
        workspace_generation=4,
        route_id=route_id,
    )


def test_command_context_is_closed_immutable_and_route_bound() -> None:
    command = ControlledOperationApplicationCommand(
        context=_context(),
        operation=ControlledOperationCommandKind.ADMIT,
        operation_id="operation-1",
        intent_digest=_digest("intent"),
        payload={"query": {"profile": "model.hmm"}},
    )

    assert command.context.route_id == "hpc:primary/hmmer"
    with pytest.raises(TypeError):
        command.payload["route"] = "local"  # type: ignore[index]
    with pytest.raises(TypeError):
        KernelCommandContext(
            command_id="command-1",
            session_id="session-1",
            actor_id="member-1",
            owner_plugin_id="enzymedesign.hmmer",
            authority_lease_id="lease-1",
            authority_generation=3,
            authority_fence=7,
            expected_session_version=11,
            extension_bundle_digest=_digest("extensions"),
            capability_binding_digest=_digest("binding"),
            idempotency_key="search-1",
            correlation_id="correlation-1",
            unexpected=True,  # type: ignore[call-arg]
        )
    with pytest.raises(ValueError, match="explicit route"):
        ControlledOperationApplicationCommand(
            context=_context(route_id=None),
            operation=ControlledOperationCommandKind.ADMIT,
            operation_id="operation-1",
            intent_digest=_digest("intent"),
            payload={},
        )


def test_kernel_receipt_has_exact_digest_and_forbids_hidden_fallback() -> None:
    receipt = KernelMutationReceipt.create(
        command_id="command-1",
        service_id="task",
        operation="attach_evidence",
        mutation_applied=True,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        entity_refs=(
            KernelEntityRef(
                entity_kind="task",
                entity_id="task-1",
                state_version=3,
                entity_digest=_digest("task"),
            ),
        ),
        event_refs=("event-1",),
        result={"accepted": True},
    )

    assert receipt.receipt_digest == canonical_sha256_digest(receipt.digest_payload())
    with pytest.raises(ValueError, match="fallback"):
        KernelMutationReceipt(
            command_id="command-1",
            service_id="task",
            operation="finish",
            mutation_applied=False,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            fallback_performed=True,
            entity_refs=(),
            event_refs=(),
            result={},
            receipt_digest=_digest("receipt"),
        )
    with pytest.raises(ValueError, match="digest mismatch"):
        KernelMutationReceipt(
            command_id="command-1",
            service_id="task",
            operation="finish",
            mutation_applied=False,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            fallback_performed=False,
            entity_refs=(),
            event_refs=(),
            result={},
            receipt_digest=_digest("wrong"),
        )


def test_extension_transaction_plan_is_namespace_confined_and_bounded() -> None:
    mutation = ExtensionStateMutation(
        mutation_kind=ExtensionStateMutationKind.UPSERT,
        namespace="enzymedesign.hmmer",
        entity_kind="search",
        entity_id="search-1",
        expected_state_version=2,
        payload={"status": "ready"},
    )
    budget = ExtensionTransactionBudget(
        max_reads=8,
        max_mutations=2,
        max_payload_bytes=65_536,
        max_duration_ms=100,
    )
    plan = ExtensionMutationPlan.create(
        plan_id="plan-1",
        participant_id="enzymedesign.hmmer.search-state",
        namespace="enzymedesign.hmmer",
        command_id="command-1",
        mutations=(mutation,),
        budget=budget,
    )
    result = ExtensionMutationResult.create(
        plan_id=plan.plan_id,
        participant_id=plan.participant_id,
        namespace=plan.namespace,
        mutation_applied=False,
        changed_records=(),
        result={"validated": True},
    )

    assert plan.plan_digest == canonical_sha256_digest(plan.digest_payload())
    assert result.result_digest == canonical_sha256_digest(result.digest_payload())
    with pytest.raises(ValueError, match="crossed its namespace"):
        ExtensionMutationPlan.create(
            plan_id="plan-2",
            participant_id="enzymedesign.hmmer.search-state",
            namespace="enzymedesign.hmmer",
            command_id="command-2",
            mutations=(
                ExtensionStateMutation(
                    mutation_kind=ExtensionStateMutationKind.DELETE,
                    namespace="openzyme.science",
                    entity_kind="attempt",
                    entity_id="attempt-1",
                    expected_state_version=1,
                    payload=None,
                ),
            ),
            budget=budget,
        )


def test_extension_state_command_has_no_arbitrary_event_hook() -> None:
    command = ExtensionStateCommand(
        context=_context(),
        participant_id="enzymedesign.hmmer.search-state",
        namespace="enzymedesign.hmmer",
        operation="record_search",
        payload={"search_id": "search-1"},
    )

    assert command.operation == "record_search"
    assert not hasattr(command, "on_any_event")


def test_projection_digest_is_bound_to_bounded_payload() -> None:
    payload = {"searches": [{"id": "search-1"}]}
    digest = canonical_sha256_digest(
        {
            "section_id": "enzymedesign.hmmer@1",
            "section_contract_digest": _digest("section"),
            "payload": payload,
            "next_cursor": None,
        }
    )
    projection = ProjectionResult(
        section_id="enzymedesign.hmmer@1",
        section_contract_digest=_digest("section"),
        payload=payload,
        next_cursor=None,
        projection_digest=digest,
    )

    assert projection.observed_digest == digest
    with pytest.raises(ValueError, match="does not match"):
        ProjectionResult(
            section_id="enzymedesign.hmmer@1",
            section_contract_digest=_digest("section"),
            payload=payload,
            next_cursor=None,
            projection_digest=_digest("wrong"),
        )


def test_subordinate_driver_protocol_exposes_no_dispatch_method() -> None:
    method_names = {
        name
        for name, value in inspect.getmembers(SubordinateDriver)
        if inspect.isfunction(value) and not name.startswith("__")
    }

    assert method_names == {"compile", "validate_result"}
    assert "dispatch" not in method_names


def test_spi_sources_do_not_import_concrete_implementation_types() -> None:
    source_root = Path(__file__).parents[1] / "src" / "openzyme_extension_spi"
    forbidden_roots = {
        "fastapi",
        "langchain",
        "langgraph",
        "openai",
        "openzyme_core",
        "openzyme_domain",
        "paramiko",
        "sqlite3",
        "subprocess",
    }
    observed: set[str] = set()
    for source_path in source_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                observed.update(
                    alias.name.split(".", maxsplit=1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                observed.add(node.module.split(".", maxsplit=1)[0])

    assert observed.isdisjoint(forbidden_roots)


def test_contract_tool_result_cannot_carry_private_runtime_handle() -> None:
    with pytest.raises(TypeError):
        ToolResult(
            call_id="call-1",
            tool_name="enzymedesign.hmmer.search",
            ok=True,
            status="ok",
            summary="complete",
            payload={},
            private_diagnostic=object(),  # type: ignore[call-arg]
        )


def test_import_performs_no_database_network_or_child_process_io() -> None:
    script = """
import os
import socket
import sqlite3
import subprocess

def forbidden(*_args, **_kwargs):
    raise AssertionError("extension SPI import attempted external I/O")

socket.create_connection = forbidden
socket.socket.connect = forbidden
sqlite3.connect = forbidden
subprocess.Popen = forbidden
os.system = forbidden

import openzyme_contracts
import openzyme_extension_spi

assert openzyme_contracts.AgentAuthorityLease.__module__ == "openzyme_contracts.authority"
assert openzyme_extension_spi.PluginManifest.__module__ == "openzyme_extension_spi.manifests"
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
