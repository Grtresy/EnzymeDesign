from __future__ import annotations

from mcp_hpc_tool_contracts.invocation import InvocationCandidate, select_invocation


def test_wrapper_failure_falls_back_to_sif_with_reason() -> None:
    wrapper = InvocationCandidate(
        mode="wrapper",
        entrypoint="/opt/tools/example",
        command=["/opt/tools/example", "--run"],
    )
    sif = InvocationCandidate(
        mode="sif", entrypoint="~/containers/example.sif", command=["apptainer", "exec"]
    )
    native = InvocationCandidate(
        mode="native", entrypoint="example", command=["example"]
    )

    selected = select_invocation(
        wrapper=wrapper,
        sif=sif,
        fallback=native,
        wrapper_check=lambda _: (False, "wrapper entrypoint not found"),
    )

    assert selected.selected.mode == "sif"
    assert len(selected.fallback) == 1
    assert selected.fallback[0].mode == "wrapper"
    assert "not found" in selected.fallback[0].reason


def test_wrapper_success_prevents_fallback_chain() -> None:
    wrapper = InvocationCandidate(
        mode="wrapper",
        entrypoint="/opt/tools/example",
        command=["/opt/tools/example", "--run"],
    )
    sif = InvocationCandidate(
        mode="sif", entrypoint="~/containers/example.sif", command=["apptainer", "exec"]
    )

    selected = select_invocation(
        wrapper=wrapper,
        sif=sif,
        fallback=None,
        wrapper_check=lambda _: (True, None),
    )

    assert selected.selected.mode == "wrapper"
    assert selected.fallback == []
