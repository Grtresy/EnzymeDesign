from __future__ import annotations

import base64
from dataclasses import dataclass
import json

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ToolInvocation
from openzyme_contracts import WorkspaceExecRequest
from openzyme_contracts import WorkspaceFilesystemMutation
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceObservation
from openzyme_contracts import WorkspaceObservationRequest
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import KernelWorkspaceToolRuntime
from openzyme_kernel import ResolvedLocalWorkspaceToolContext
from openzyme_kernel import WorkspaceOperationOutcome
from openzyme_kernel import WorkspaceOperationSettlementState
from openzyme_kernel import build_kernel_workspace_tool_runtimes
from openzyme_kernel import kernel_workspace_tool_specs


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


def _command_context(*, route_id: str | None = "route-local") -> KernelCommandContext:
    return KernelCommandContext(
        command_id="placeholder-command",
        session_id="session-1",
        actor_id="member-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=7,
        expected_session_version=5,
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("capability-binding"),
        idempotency_key="placeholder-idempotency",
        correlation_id="correlation-1",
        workspace_generation=3,
        route_id=route_id,
    )


@dataclass
class RecordingContextResolver:
    calls: list[tuple[str, bool]]

    def resolve(
        self,
        invocation: ToolInvocation,
        *,
        effectful: bool,
    ) -> ResolvedLocalWorkspaceToolContext:
        self.calls.append((invocation.tool_name, effectful))
        return ResolvedLocalWorkspaceToolContext(
            binding=_binding(),
            command_context=_command_context(
                route_id="route-local" if effectful else None
            ),
            process_epoch=11,
        )


class RecordingCoordinator:
    def __init__(self) -> None:
        self.observations: list[WorkspaceObservationRequest] = []
        self.mutations: list[WorkspaceFilesystemMutation] = []
        self.processes: list[WorkspaceExecRequest] = []

    def observe(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspaceObservationRequest,
    ) -> WorkspaceObservation:
        assert context.session_id == request.binding.session_id
        self.observations.append(request)
        payload = json.dumps(
            {
                "path": request.path,
                "operation": request.operation.value,
                "dirty": False,
            },
            sort_keys=True,
        ).encode()
        return WorkspaceObservation(
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            operation=request.operation,
            result_digest=f"sha256:{__import__('hashlib').sha256(payload).hexdigest()}",
            bounded_payload=payload,
        )

    def mutate_filesystem(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationOutcome:
        assert context.idempotency_key == request.idempotency_key
        self.mutations.append(request)
        return _outcome(
            request.operation_id,
            request.binding,
            {"path": request.path, "content_digest": _digest("after")},
        )

    def execute_process(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspaceExecRequest,
    ) -> WorkspaceOperationOutcome:
        assert context.idempotency_key == request.idempotency_key
        self.processes.append(request)
        return _outcome(
            request.operation_id,
            request.binding,
            {
                "returncode": 0,
                "stdout": "ok",
                "stderr": "",
                "fallback_performed": False,
            },
        )


def _outcome(
    operation_id: str,
    binding: WorkspaceRuntimeBinding,
    result: dict[str, object],
) -> WorkspaceOperationOutcome:
    receipt = WorkspaceOperationReceipt.create(
        operation_id=operation_id,
        workspace_id=binding.workspace_id,
        generation=binding.generation,
        state_version=binding.state_version,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        mutation_applied=True,
        result_payload=json.dumps(result, sort_keys=True).encode(),
    )
    return WorkspaceOperationOutcome(
        operation_id=operation_id,
        intent_digest=_digest(operation_id),
        workspace_id=binding.workspace_id,
        generation=binding.generation,
        state_version=binding.state_version,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        mutation_applied=True,
        settlement_state=WorkspaceOperationSettlementState.SETTLED,
        controlled_operation_receipt_digest=_digest("controlled-" + operation_id),
        adapter_receipt=receipt,
    )


def _invocation(tool_name: str, arguments: dict[str, object]) -> ToolInvocation:
    return ToolInvocation(
        call_id="call-1",
        tool_name=tool_name,
        arguments=arguments,
        session_id="session-1",
        agent_member_id="member-1",
        affordance_snapshot_digest=_digest("affordance"),
    )


def _runtime(
    tool_name: str,
) -> tuple[KernelWorkspaceToolRuntime, RecordingCoordinator, RecordingContextResolver]:
    coordinator = RecordingCoordinator()
    resolver = RecordingContextResolver([])
    return (
        KernelWorkspaceToolRuntime(
            tool_name=tool_name,
            coordinator=coordinator,  # type: ignore[arg-type]
            context_resolver=resolver,
        ),
        coordinator,
        resolver,
    )


def test_base_catalog_is_closed_and_has_no_workspace_or_credential_input() -> None:
    specs = {item.tool_name: item for item in kernel_workspace_tool_specs()}

    assert set(specs) == {
        "workspace.status",
        "workspace.fs.read",
        "workspace.fs.list",
        "workspace.fs.mutate",
        "workspace.exec",
    }
    for spec in specs.values():
        properties = spec.input_schema["properties"]
        assert "workspace_id" not in properties
        assert "credential" not in properties
        assert "target_id" not in properties
        assert spec.input_schema["additionalProperties"] is False


def test_status_read_and_list_are_query_only_local_observations() -> None:
    for tool_name, arguments, expected_operation in (
        ("workspace.status", {}, "status"),
        ("workspace.fs.read", {"path": "notes.txt"}, "read"),
        ("workspace.fs.list", {"path": "results"}, "list"),
    ):
        runtime, coordinator, resolver = _runtime(tool_name)

        result = runtime.invoke(_invocation(tool_name, arguments))

        assert result.ok is True
        assert resolver.calls == [(tool_name, False)]
        assert coordinator.observations[0].operation.value == expected_operation
        assert result.payload["mutation_applied"] is False  # type: ignore[index]


def test_structured_mutation_decodes_content_and_binds_call_identity() -> None:
    runtime, coordinator, resolver = _runtime("workspace.fs.mutate")

    result = runtime.invoke(
        _invocation(
            "workspace.fs.mutate",
            {
                "operation": "write",
                "path": "results/output.txt",
                "content_base64": base64.b64encode(b"result").decode(),
            },
        )
    )

    request = coordinator.mutations[0]
    assert result.ok is True
    assert resolver.calls == [("workspace.fs.mutate", True)]
    assert request.content == b"result"
    assert request.binding.workspace_id == "workspace-1"
    assert request.authority_lease_id == "lease-1"
    assert request.operation_id.startswith("workspace-operation-")
    assert result.payload["publication_performed"] is False  # type: ignore[index]
    assert result.payload["task_transition_performed"] is False  # type: ignore[index]


def test_exec_preserves_exact_argv_and_exposes_no_credential_channel() -> None:
    runtime, coordinator, resolver = _runtime("workspace.exec")
    argv = ["/bin/sh", "-lc", "printf explicit-shell"]

    result = runtime.invoke(
        _invocation(
            "workspace.exec",
            {
                "argv": argv,
                "cwd": "analysis",
                "timeout_seconds": 30,
                "max_output_bytes": 4096,
            },
        )
    )

    request = coordinator.processes[0]
    assert result.ok is True
    assert resolver.calls == [("workspace.exec", True)]
    assert request.argv == tuple(argv)
    assert request.cwd == "analysis"
    assert request.process_epoch == 11

    rejected = runtime.invoke(
        _invocation(
            "workspace.exec",
            {
                "argv": ["ssh", "cluster"],
                "credential": {
                    "service_id": "hpc-native:hpc-primary",
                    "target_id": "hpc-primary",
                },
            },
        )
    )
    assert rejected.ok is False
    assert rejected.error_code == "invalid_tool_arguments"
    assert len(coordinator.processes) == 1


def test_local_workspace_id_is_rejected_before_context_resolution() -> None:
    runtime, coordinator, resolver = _runtime("workspace.fs.read")

    result = runtime.invoke(
        _invocation(
            "workspace.fs.read",
            {"path": "note.txt", "workspace_id": "other-workspace"},
        )
    )

    assert result.ok is False
    assert result.error_code == "workspace_id_forbidden"
    assert resolver.calls == []
    assert coordinator.observations == []
    assert result.payload["effect_certainty"] == "no_effect"  # type: ignore[index]


def test_runtime_factory_matches_declared_contracts() -> None:
    coordinator = RecordingCoordinator()
    resolver = RecordingContextResolver([])

    runtimes = build_kernel_workspace_tool_runtimes(
        coordinator=coordinator,  # type: ignore[arg-type]
        context_resolver=resolver,
    )

    assert [item.contract.tool_name for item in runtimes] == sorted(
        item.tool_name for item in kernel_workspace_tool_specs()
    )
