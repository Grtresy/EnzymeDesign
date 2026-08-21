from __future__ import annotations

from dataclasses import replace
import importlib.metadata

import pytest

import openzyme_contracts
from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ExtensionCapabilityFact
from openzyme_contracts import ResourceCapabilityFact
from openzyme_contracts import ResourceCapabilityKind
from openzyme_contracts import ToolAffordance
from openzyme_contracts import ToolAffordanceBlocker
from openzyme_contracts import ToolAffordanceState
from openzyme_contracts import ToolSpec
from openzyme_contracts import WorkspaceExecRequest
from openzyme_contracts import WorkspaceFilesystemMutation
from openzyme_contracts import WorkspaceFilesystemMutationKind
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import WorkspaceTransferDirection
from openzyme_contracts import WorkspaceTransferRequest
from openzyme_contracts import canonical_sha256_digest


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _local_binding() -> WorkspaceRuntimeBinding:
    return WorkspaceRuntimeBinding(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="member-1",
        generation=2,
        state_version=3,
        root_identity_digest=_digest("root"),
        provider_id="openzyme.workspace.git-lfs",
        target_id="local:host",
    )


def test_workspace_generation_is_closed_and_only_ready_exposes_runtime_binding() -> None:
    generation = WorkspaceGeneration(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="member-1",
        generation=2,
        state_version=3,
        status=WorkspaceGenerationStatus.READY,
        provider_id="openzyme.workspace.git-lfs",
        target_id="local:host",
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:03+00:00",
        root_identity_digest=_digest("root"),
        transition_receipt_digest=_digest("receipt"),
        controlled_operation_id="operation-1",
    )

    restored = WorkspaceGeneration.from_dict(generation.to_dict())
    assert restored == generation
    assert restored.runtime_binding().generation == 2
    with pytest.raises(ValueError, match="closed schema"):
        WorkspaceGeneration.from_dict({**generation.to_dict(), "host_path": "/tmp/x"})
    with pytest.raises(ValueError, match="only a ready"):
        replace(
            generation,
            status=WorkspaceGenerationStatus.RETIRING,
            transition_receipt_digest=None,
            controlled_operation_id=None,
        ).runtime_binding()


def test_contracts_distribution_has_no_runtime_dependencies() -> None:
    metadata = importlib.metadata.metadata("openzyme-contracts")
    requirements = metadata.get_all("Requires-Dist") or []
    runtime_requirements = [
        requirement for requirement in requirements if "extra ==" not in requirement
    ]

    assert runtime_requirements == []
    assert not hasattr(openzyme_contracts, "AgentCapabilityLease")


def test_canonical_tool_contract_is_order_independent_and_frozen() -> None:
    first = ToolSpec(
        tool_name="workspace.fs.read",
        description="Read a bounded workspace file.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
        output_schema={"type": "object"},
        required_authorities=("workspace.fs.read",),
    )
    second = ToolSpec(
        tool_name="workspace.fs.read",
        description="Read a bounded workspace file.",
        input_schema={
            "properties": {"path": {"type": "string"}},
            "type": "object",
        },
        output_schema={"type": "object"},
        required_authorities=("workspace.fs.read",),
    )

    assert first.contract_digest == second.contract_digest
    with pytest.raises(TypeError):
        first.input_schema["additionalProperties"] = False  # type: ignore[index]


def test_authority_is_distinct_from_resource_availability() -> None:
    grant = AuthorityGrant.create(
        grant_id="grant-1",
        scope_id="hpc:primary",
        operations=("hpc.workspace.process.exec",),
        generation=1,
        fence=2,
    )
    lease = AgentAuthorityLease.create(
        lease_id="lease-1",
        session_id="session-1",
        agent_member_id="member-1",
        grants=(grant,),
        generation=1,
        fence=2,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at="2026-08-19T00:00:00Z",
        expires_at="2026-08-19T01:00:00Z",
    )
    extension_fact = ExtensionCapabilityFact(
        capability_id="enzymedesign.hmmer",
        contract_id="enzymedesign.hmmer@1",
        provider_component_id="enzymedesign.hmmer",
        provider_version="1.0.0",
        contract_digest=_digest("hmmer-contract"),
        activation_epoch=1,
        contract_version="1",
        operations=("hmmbuild", "hmmsearch"),
    )
    resource_fact = ResourceCapabilityFact(
        capability_id="software.hmmer",
        kind=ResourceCapabilityKind.SOFTWARE,
        target_id="hpc:primary",
        inventory_generation=7,
        qualification_digest=_digest("hmmer-qualification"),
        environment_digest=_digest("hmmer-environment"),
        inventory_digest=_digest("hmmer-inventory"),
        operations=("hmmsearch", "hmmbuild"),
        version="3.4",
    )

    assert lease.allows(
        "hpc.workspace.process.exec",
        scope_id="hpc:primary",
    )
    assert extension_fact.capability_id != resource_fact.capability_id
    assert not lease.allows("hpc.scheduler.submit", scope_id="hpc:primary")


def test_affordance_visibility_is_closed_and_does_not_leak_hidden_routes() -> None:
    blocked = ToolAffordance(
        tool_name="enzymedesign.hmmer.search",
        tool_contract_digest=_digest("tool"),
        state=ToolAffordanceState.BLOCKED_QUALIFICATION,
        required_authorities=("external_compute",),
        blockers=(
            ToolAffordanceBlocker(
                code="software_requirement_unsatisfied",
                requirement="software.hmmer>=3.3,<4",
                target_id="hpc:primary",
            ),
        ),
    )
    hidden = ToolAffordance(
        tool_name="operator.target.qualify",
        tool_contract_digest=_digest("operator-tool"),
        state=ToolAffordanceState.HIDDEN,
        required_authorities=("operator.target.qualify",),
    )

    assert not blocked.state.model_visible
    assert hidden.to_dict()["route_ids"] == []
    with pytest.raises(ValueError, match="must not disclose"):
        ToolAffordance(
            tool_name="operator.target.qualify",
            tool_contract_digest=_digest("operator-tool"),
            state=ToolAffordanceState.HIDDEN,
            required_authorities=(),
            route_ids=("hpc:primary/operator",),
        )


@pytest.mark.parametrize(
    "path",
    (
        "/etc/passwd",
        "../other-agent/file",
        "results/*.csv",
        "results\\file.csv",
    ),
)
def test_workspace_mutation_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError):
        WorkspaceFilesystemMutation(
            operation_id="operation-1",
            binding=_local_binding(),
            operation=WorkspaceFilesystemMutationKind.REMOVE,
            path=path,
            idempotency_key="remove-1",
            authority_lease_id="lease-1",
            authority_generation=2,
            authority_fence=3,
        )


def test_workspace_exec_is_bounded_argv_and_local_binding_carries_no_hpc_proof() -> (
    None
):
    request = WorkspaceExecRequest(
        operation_id="operation-1",
        binding=_local_binding(),
        argv=("python", "script.py", "--input", "data.csv"),
        cwd="analysis",
        timeout_seconds=30,
        max_output_bytes=65_536,
        idempotency_key="exec-1",
        authority_lease_id="lease-1",
        authority_generation=2,
        authority_fence=3,
        process_epoch=4,
    )

    assert request.argv[0] == "python"
    assert request.binding.target_qualification_digest is None
    with pytest.raises(ValueError, match="argv"):
        WorkspaceExecRequest(
            operation_id="operation-2",
            binding=_local_binding(),
            argv=(),
            cwd=".",
            timeout_seconds=30,
            max_output_bytes=65_536,
            idempotency_key="exec-2",
            authority_lease_id="lease-1",
            authority_generation=2,
            authority_fence=3,
            process_epoch=4,
        )

    with pytest.raises(ValueError, match="interactive"):
        WorkspaceExecRequest(
            operation_id="operation-3",
            binding=_local_binding(),
            argv=("python", "script.py"),
            cwd=".",
            timeout_seconds=30,
            max_output_bytes=65_536,
            idempotency_key="exec-3",
            authority_lease_id="lease-1",
            authority_generation=2,
            authority_fence=3,
            process_epoch=4,
            interactive=True,
        )
    with pytest.raises(ValueError, match="background"):
        WorkspaceExecRequest(
            operation_id="operation-4",
            binding=_local_binding(),
            argv=("python", "script.py"),
            cwd=".",
            timeout_seconds=30,
            max_output_bytes=65_536,
            idempotency_key="exec-4",
            authority_lease_id="lease-1",
            authority_generation=2,
            authority_fence=3,
            process_epoch=4,
            background=True,
        )


def test_workspace_intents_and_receipts_are_content_bound() -> None:
    request = WorkspaceFilesystemMutation(
        operation_id="operation-1",
        binding=_local_binding(),
        operation=WorkspaceFilesystemMutationKind.WRITE,
        path="results/output.txt",
        content=b"result",
        idempotency_key="write-1",
        authority_lease_id="lease-1",
        authority_generation=2,
        authority_fence=3,
    )
    changed = WorkspaceFilesystemMutation(
        operation_id="operation-1",
        binding=_local_binding(),
        operation=WorkspaceFilesystemMutationKind.WRITE,
        path="results/output.txt",
        content=b"different",
        idempotency_key="write-1",
        authority_lease_id="lease-1",
        authority_generation=2,
        authority_fence=3,
    )
    receipt = WorkspaceOperationReceipt.create(
        operation_id=request.operation_id,
        workspace_id=request.binding.workspace_id,
        generation=request.binding.generation,
        state_version=request.binding.state_version,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        mutation_applied=True,
        result_payload=b'{"returncode":0}',
    )

    assert request.intent_digest != changed.intent_digest
    assert receipt.receipt_digest == canonical_sha256_digest(receipt.digest_payload())
    assert receipt.digest_payload()["result_payload_size"] == 16
    with pytest.raises(ValueError, match="digest mismatch"):
        replace(receipt, state_version=receipt.state_version + 1)


def test_workspace_transfer_binds_opaque_manifest_budget_and_deadline() -> None:
    request = WorkspaceTransferRequest(
        operation_id="operation-1",
        binding=_local_binding(),
        direction=WorkspaceTransferDirection.DOWNLOAD,
        path="imports/model.bin",
        transfer_ref="transfer:model-1",
        transfer_manifest_digest=_digest("transfer-manifest"),
        max_bytes=8_388_608,
        timeout_seconds=120,
        idempotency_key="download-1",
        authority_lease_id="lease-1",
        authority_generation=2,
        authority_fence=3,
    )

    assert request.intent_payload()["transfer_ref"] == "transfer:model-1"
    assert request.intent_payload()["transfer_manifest_digest"] == _digest(
        "transfer-manifest"
    )
    assert request.intent_payload()["max_bytes"] == 8_388_608

    for unsafe_ref in (
        "/host/private.bin",
        "../other-workspace",
        "https://example.invalid/blob",
    ):
        with pytest.raises(ValueError, match="opaque"):
            replace(request, transfer_ref=unsafe_ref)

    with pytest.raises(ValueError, match="timeout_seconds"):
        replace(request, timeout_seconds=0)
    with pytest.raises(ValueError, match="max_bytes"):
        replace(request, max_bytes=0)


def test_dispatch_in_doubt_cannot_claim_mutation_fact() -> None:
    with pytest.raises(ValueError, match="cannot claim mutation certainty"):
        WorkspaceOperationReceipt.create(
            operation_id="operation-1",
            workspace_id="workspace-1",
            generation=1,
            state_version=1,
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            mutation_applied=False,
        )


def test_no_effect_receipt_cannot_claim_mutation_or_fallback() -> None:
    with pytest.raises(ValueError, match="cannot report a mutation"):
        WorkspaceOperationReceipt(
            operation_id="operation-1",
            workspace_id="workspace-1",
            generation=1,
            state_version=1,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            mutation_applied=True,
            fallback_performed=False,
            receipt_digest=_digest("receipt"),
        )

    with pytest.raises(ValueError, match="hidden fallback"):
        WorkspaceOperationReceipt(
            operation_id="operation-1",
            workspace_id="workspace-1",
            generation=1,
            state_version=1,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            fallback_performed=True,
            receipt_digest=_digest("receipt"),
        )
