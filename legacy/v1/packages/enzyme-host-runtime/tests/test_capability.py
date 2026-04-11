from __future__ import annotations

from pathlib import Path

from enzyme_host_runtime.capability import CapabilityDetailContract
from enzyme_host_runtime.capability import CapabilitySummary
from enzyme_host_runtime.capability import CapabilityToolDescriptor
from enzyme_host_runtime.capability import CapabilityVisibilityScope
from enzyme_host_runtime.capability import HostCapabilityGateway
from enzyme_host_runtime.capability import InspectedCapabilityBinding
from enzyme_host_runtime.capability import StaticCapabilityAdapter
from enzyme_host_runtime.capability import capability_context_payload
from enzyme_host_runtime.capability import configured_capability_summaries
from enzyme_host_runtime.capability import visible_capability_bindings
from enzyme_host_runtime.execution import ExecutionResult
from enzyme_host_runtime.plan_runtime import PlanStep


class _FakeExecutor:
    def run_step(self, project_root: Path, episode_id: str, step: PlanStep) -> ExecutionResult:
        del project_root, episode_id
        return ExecutionResult(
            run_id="cap-run-1",
            status="completed",
            manifest_payload={
                "tool": step.tool,
                "status": "completed",
                "output_refs": [{"path": "outputs/demo.sdf", "kind": "artifact"}],
            },
        )

    def supports(self, tool: str) -> bool:
        return tool.endswith("_tool")


def _adapter(
    capability_id: str,
    *,
    selectable: bool = True,
    summary_override: str | None = None,
    metadata: dict[str, object] | None = None,
) -> StaticCapabilityAdapter:
    return StaticCapabilityAdapter(
        capability_id=capability_id,
        server_name=f"{capability_id}-server",
        title=f"{capability_id} title",
        use_when=["needed for testing"],
        result_kind="test artifacts",
        cost_hint="low",
        selection_hint="inspect for tests",
        tool_descriptors=[
            CapabilityToolDescriptor(
                tool=f"{capability_id}_tool",
                title="Demo tool",
                description="Runs the demo tool.",
                input_keys=["input"],
                result_kind="artifact",
            )
        ],
        executor=_FakeExecutor(),
        selectable=selectable,
        summary_override=summary_override,
        metadata={"source": "test", **dict(metadata or {})},
    )


def test_gateway_lists_visible_summaries_and_keeps_hidden_capabilities_optional() -> None:
    gateway = HostCapabilityGateway(
        [
            _adapter("visible-cap"),
            _adapter("hidden-cap", selectable=False),
        ]
    )

    visible = gateway.list_summaries()
    all_items = gateway.list_summaries(include_hidden=True)

    assert [item.capability_id for item in visible] == ["visible-cap"]
    assert [item.capability_id for item in all_items] == ["hidden-cap", "visible-cap"]


def test_static_adapter_prefers_summary_override_and_inspect_returns_detail_contract() -> None:
    gateway = HostCapabilityGateway([_adapter("override-cap", summary_override="host override summary")])

    summary = gateway.list_summaries()[0]
    detail = gateway.inspect("override-cap")

    assert summary.summary == "host override summary"
    assert detail.summary == "host override summary"
    assert detail.tools[0].tool == "override-cap_tool"


def test_static_adapter_uses_metadata_summary_before_auto_generated_fallback() -> None:
    gateway = HostCapabilityGateway(
        [_adapter("metadata-cap", metadata={"summary": "metadata supplied summary"})]
    )

    summary = gateway.list_summaries()[0]
    detail = gateway.inspect("metadata-cap")

    assert summary.summary == "metadata supplied summary"
    assert detail.summary == "metadata supplied summary"


def test_capability_context_payload_round_trips_summaries_and_visibility_scope() -> None:
    summary = CapabilitySummary(
        capability_id="cap-a",
        server_name="server-a",
        title="Capability A",
        summary="summary",
        use_when=["when needed"],
        result_kind="artifact",
        cost_hint="low",
        inspect_handle="cap-a",
        tool_names=["tool-a"],
    )
    binding = InspectedCapabilityBinding(
        contract=CapabilityDetailContract(
            capability_id="cap-a",
            server_name="server-a",
            title="Capability A",
            summary="summary",
            use_when=["when needed"],
            result_kind="artifact",
            cost_hint="low",
            selection_hint="inspect me",
            tools=[
                CapabilityToolDescriptor(
                    tool="tool-a",
                    title="Tool A",
                    description="Does work.",
                    input_keys=["input"],
                    result_kind="artifact",
                )
            ],
        ),
        scope=CapabilityVisibilityScope(
            episode_id="ep-1",
            active_state_version=3,
            role="host-agent",
        ),
        inspected_at="2026-03-14T00:00:00+00:00",
    )

    payload = capability_context_payload([summary], [binding])

    assert configured_capability_summaries(payload)[0].capability_id == "cap-a"
    assert visible_capability_bindings(
        payload,
        episode_id="ep-1",
        active_state_version=3,
        role="host-agent",
    )[0].contract.capability_id == "cap-a"
    assert (
        visible_capability_bindings(
            payload,
            episode_id="ep-1",
            active_state_version=2,
            role="host-agent",
        )
        == []
    )


def test_gateway_normalizes_execution_results_from_adapter_output_refs() -> None:
    gateway = HostCapabilityGateway([_adapter("exec-cap")], executor=_FakeExecutor())

    result = gateway.run_step(
        Path("/tmp/demo"),
        "ep-1",
        PlanStep(step_id="step-1", tool="exec-cap_tool", payload={"id": "step-1"}),
    )

    assert result.capability_id == "exec-cap"
    assert result.output_refs == [{"path": "outputs/demo.sdf", "kind": "artifact"}]
