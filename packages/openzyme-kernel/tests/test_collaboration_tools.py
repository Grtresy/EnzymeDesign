from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ToolInvocation
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_kernel.collaboration_tools import CollaborationToolApplications
from openzyme_kernel.collaboration_tools import KernelCollaborationToolRuntime
from openzyme_kernel.collaboration_tools import ResolvedCollaborationToolContext
from openzyme_kernel.collaboration_tools import build_kernel_collaboration_tool_runtimes
from openzyme_kernel.collaboration_tools import kernel_collaboration_declared_tool_entries
from openzyme_kernel.collaboration_tools import kernel_collaboration_tool_specs
from openzyme_kernel.errors import KernelContractError


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _command_context() -> KernelCommandContext:
    return KernelCommandContext(
        command_id="runtime-command-1",
        session_id="session-1",
        actor_id="member-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="authority-1",
        authority_generation=2,
        authority_fence=3,
        expected_session_version=4,
        extension_bundle_digest=_digest("extension"),
        capability_binding_digest=_digest("binding"),
        idempotency_key="runtime-command-1",
        correlation_id="correlation-1",
        workspace_generation=1,
    )


@dataclass
class FakeResolver:
    failure: KernelContractError | None = None

    def __post_init__(self) -> None:
        self.effectful: list[bool] = []

    def resolve(self, invocation, *, effectful):  # noqa: ANN001
        self.effectful.append(effectful)
        if self.failure is not None:
            raise self.failure
        return ResolvedCollaborationToolContext(
            command_context=_command_context(),
            runtime_command_id="runtime-command-1",
            workflow_authority_id="workflow-authority-1",
            workflow_authority_epoch=5,
            workflow_authority_digest=_digest("workflow-authority"),
        )


class FakeWorld:
    def inspect(self, *, context, arguments):  # noqa: ANN001
        return {
            "runtime_command_id": context.runtime_command_id,
            "task_status": "in_progress",
            "sections": list(arguments.get("sections", ())),
        }


class FakeApplication:
    def __init__(self) -> None:
        self.commands = []

    def execute(self, command):  # noqa: ANN001
        self.commands.append(command)
        task_transition = getattr(command, "operation", None).value == "finish"
        return _receipt(
            command.context.command_id,
            operation=command.operation.value,
            result={"task_transition_performed": task_transition},
        )


class FakeProtocol:
    def __init__(self) -> None:
        self.delegations = []
        self.messages = []

    def delegate(self, command):  # noqa: ANN001
        self.delegations.append(command)
        return _receipt(
            command.context.command_id,
            operation="delegate",
            result={
                "recipient_runtime_executed": False,
                "task_transition_performed": False,
            },
        )

    def send(self, command):  # noqa: ANN001
        self.messages.append(command)
        return _receipt(
            command.context.command_id,
            operation="send",
            result={
                "recipient_runtime_executed": False,
                "task_transition_performed": False,
            },
        )


def _receipt(
    command_id: str,
    *,
    operation: str,
    result: dict[str, object] | None = None,
) -> KernelMutationReceipt:
    return KernelMutationReceipt.create(
        command_id=command_id,
        service_id="openzyme.kernel.fake-application",
        operation=operation,
        mutation_applied=True,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        result=result or {"task_transition_performed": False},
    )


def _applications() -> tuple[CollaborationToolApplications, FakeApplication, FakeProtocol]:
    application = FakeApplication()
    protocol = FakeProtocol()
    return (
        CollaborationToolApplications(
            world=FakeWorld(),
            collaboration=application,
            tasks=application,
            protocol=protocol,
            approvals=application,
        ),
        application,
        protocol,
    )


def _invocation(tool_name: str, arguments: dict[str, object]) -> ToolInvocation:
    return ToolInvocation(
        call_id=f"call-{tool_name.replace('.', '-')}",
        tool_name=tool_name,
        arguments=arguments,
        session_id="session-1",
        agent_member_id="member-1",
        task_id="task-1",
        lane_id="lane-1",
        affordance_snapshot_digest=_digest("affordance"),
    )


def test_stable_collaboration_catalog_is_closed_and_kernel_owned() -> None:
    names = tuple(spec.tool_name for spec in kernel_collaboration_tool_specs())
    entries = kernel_collaboration_declared_tool_entries()

    assert names == (
        "world.inspect",
        "capabilities.inspect",
        "task.create",
        "task.update",
        "task.finish",
        "task.delegate",
        "protocol.send",
        "approval.request",
    )
    assert {entry.contract.tool_name for entry in entries} == set(names)
    assert {entry.owner_component_id for entry in entries} == {"openzyme.kernel"}
    assert all(not entry.requires_explicit_route for entry in entries)


def test_world_inspect_reads_canonical_facts_without_mutation() -> None:
    applications, _, _ = _applications()
    resolver = FakeResolver()
    runtime = KernelCollaborationToolRuntime(
        "world.inspect",
        applications,
        resolver,
    )

    result = runtime.invoke(
        _invocation("world.inspect", {"sections": ["tasks", "workflow"]})
    )

    assert result.ok is True
    assert result.payload["facts"]["task_status"] == "in_progress"
    assert result.payload["mutation_applied"] is False
    assert resolver.effectful == [False]


def test_task_update_rejects_terminal_status_before_application_mutation() -> None:
    applications, application, _ = _applications()
    runtime = KernelCollaborationToolRuntime(
        "task.update",
        applications,
        FakeResolver(),
    )

    result = runtime.invoke(
        _invocation(
            "task.update",
            {
                "task_id": "task-1",
                "expected_task_version": 4,
                "updates": {"status": "completed"},
            },
        )
    )

    assert result.ok is False
    assert result.error_code == "task_terminal_transition_requires_finish"
    assert result.payload["mutation_applied"] is False
    assert application.commands == []


def test_task_finish_is_the_only_explicit_terminal_verb() -> None:
    applications, application, _ = _applications()
    runtime = KernelCollaborationToolRuntime(
        "task.finish",
        applications,
        FakeResolver(),
    )

    result = runtime.invoke(
        _invocation(
            "task.finish",
            {
                "task_id": "task-1",
                "expected_task_version": 4,
                "terminal_status": "completed",
                "evidence_refs": [],
            },
        )
    )

    assert result.ok is True
    assert result.terminal_action == "task.finish"
    assert application.commands[-1].operation.value == "finish"
    assert application.commands[-1].payload["terminal_status"] == "completed"


def test_delegate_injects_exact_workflow_authority_and_only_enqueues() -> None:
    applications, _, protocol = _applications()
    runtime = KernelCollaborationToolRuntime(
        "task.delegate",
        applications,
        FakeResolver(),
    )

    result = runtime.invoke(
        _invocation(
            "task.delegate",
            {
                "protocol_ref": "protocol-1",
                "task_id": "task-1",
                "recipient_actor_id": "member-2",
                "instruction": "Inspect the bounded evidence.",
                "workflow_refs": ["workflow.report@1"],
            },
        )
    )

    assert result.ok is True
    command = protocol.delegations[-1]
    assert command.payload["workflow_authority_id"] == "workflow-authority-1"
    assert command.payload["workflow_authority_epoch"] == 5
    assert command.payload["workflow_refs"] == ("workflow.report@1",)
    assert result.payload["result"]["recipient_runtime_executed"] is False
    assert result.payload["result"]["runtime_executed"] is False


def test_stale_runtime_scope_is_a_readable_no_effect_tool_error() -> None:
    applications, _, protocol = _applications()
    resolver = FakeResolver(
        KernelContractError(
            "workflow_authority_epoch_stale",
            "Workflow authority changed before dispatch.",
        )
    )
    runtime = KernelCollaborationToolRuntime(
        "protocol.send",
        applications,
        resolver,
    )

    result = runtime.invoke(
        _invocation(
            "protocol.send",
            {
                "protocol_ref": "protocol-1",
                "recipient_actor_id": "member-2",
                "message_type": "status",
                "content": "Still in progress.",
            },
        )
    )

    assert result.ok is False
    assert result.error_code == "workflow_authority_epoch_stale"
    assert result.payload["effect_certainty"] == "no_effect"
    assert protocol.messages == []


def test_runtime_builder_excludes_gateway_owned_capability_inspection() -> None:
    applications, _, _ = _applications()
    runtimes = build_kernel_collaboration_tool_runtimes(
        applications=applications,
        context_resolver=FakeResolver(),
    )

    assert {runtime.tool_name for runtime in runtimes} == {
        "world.inspect",
        "task.create",
        "task.update",
        "task.finish",
        "task.delegate",
        "protocol.send",
        "approval.request",
    }
