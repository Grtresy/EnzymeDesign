from __future__ import annotations

import inspect

import pytest

from openzyme_pipeline import client


def test_controlled_operation_sends_only_plan_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def _call(method: str, params: dict[str, object]) -> dict[str, str]:
        calls.append((method, params))
        return {"operation_id": "op_host_owned_result"}

    monkeypatch.setattr(client, "call", _call)

    result = client.controlled_operation(
        sdk_module="bio",
        function_name="ncbi_fetch_proteins",
        route_policy_id="bio.ncbi_fetch_proteins.provider:v1",
        params={"accessions": ["AAB57849.1"]},
        expected_outputs={"kind": "fasta"},
        resource_estimate={"requests": 1},
    )

    assert result == {"operation_id": "op_host_owned_result"}
    assert len(calls) == 1
    method, envelope = calls[0]
    assert method == "s10.controlled_operation"
    assert envelope["schema_version"] == "s12.adapter_envelope.v1"
    assert "adapter_result" not in envelope
    assert "result_summary" not in envelope


def test_controlled_operation_api_does_not_expose_host_result_fields() -> None:
    parameters = inspect.signature(client.controlled_operation).parameters

    assert "adapter_result" not in parameters
    assert "result_summary" not in parameters
