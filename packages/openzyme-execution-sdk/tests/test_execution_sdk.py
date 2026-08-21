from __future__ import annotations

from dataclasses import asdict

import pytest

from openzyme_execution_sdk import CONTROL_SOCKET_FRAME_MAX_BYTES
from openzyme_execution_sdk import ControlClient
from openzyme_execution_sdk import ExecutionSdkError
from openzyme_execution_sdk import PipelineSdkError
from openzyme_execution_sdk import canonical_digest
from openzyme_execution_sdk.workspace_revision import WorkspaceRevisionJob
from openzyme_execution_sdk import workload as workload_sdk
from openzyme_execution_contracts import ExecutionRouteIdentity
from openzyme_execution_contracts import ExecutionWorkloadSpec
from openzyme_execution_contracts import canonical_execution_wire_digest


def test_sdk_exports_domain_neutral_bounded_transport_contract() -> None:
    assert CONTROL_SOCKET_FRAME_MAX_BYTES == 4 * 1024 * 1024
    assert PipelineSdkError is ExecutionSdkError
    assert canonical_digest({"b": 2, "a": 1}) == canonical_digest({"a": 1, "b": 2})


@pytest.mark.parametrize(
    "payload",
    [
        b"[]",
        b'{"jsonrpc":"2.0","id":"wrong","result":{}}',
        b'{"jsonrpc":"2.0","id":"rpc_expected","result":{},"error":{}}',
        b'{"jsonrpc":"2.0","id":"rpc_expected","result":{"value":NaN}}',
        b'{"jsonrpc":"2.0","id":"rpc_expected","result":{},"result":{}}',
    ],
)
def test_sdk_rejects_non_closed_or_identity_drifted_responses(payload: bytes) -> None:
    with pytest.raises(ExecutionSdkError) as error:
        ControlClient._decode_response_frame(payload, request_id="rpc_expected")

    assert error.value.error_code == "sandbox_transport_response_invalid"
    assert error.value.retryable is False


def test_workspace_revision_job_uses_only_opaque_public_identity() -> None:
    job = WorkspaceRevisionJob(
        execution_id="execution_1",
        operation_id="operation_1",
        request_id="request_1",
        source_revision_id="revision_1",
        source_commit="a" * 40,
        source_tree="b" * 40,
        cwd="analysis/run-1",
    )

    assert asdict(job)["cwd"] == "analysis/run-1"
    assert not hasattr(job, "host_path")
    assert not hasattr(job, "remote_root")
    assert not hasattr(job, "scheduler_job_id")


def test_workload_protocol_sends_only_typed_workload_route_and_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = "sha256:" + "1" * 64
    workload_payload: dict[str, object] = {
        "schema_version": "execution_workload_spec@1",
        "workload_id": "workload_1",
        "workload_contract": "example.compute@1",
        "entry_point": "example.compute@1",
        "argv": ["compute", "input/data.txt"],
        "cwd": "run",
        "resource_policy_digest": digest,
        "environment_policy_digest": digest,
        "inputs": [
            {
                "revision_id": "revision_1",
                "commit": "a" * 40,
                "tree": "b" * 40,
                "path": "input/data.txt",
                "content_digest": digest,
            }
        ],
        "result_contract": {
            "contract_id": "example.result@1",
            "schema_digest": digest,
            "result_root": "results",
        },
        "capability_requirements": [],
    }
    workload_payload["workload_digest"] = canonical_execution_wire_digest(
        workload_payload
    )
    workload = ExecutionWorkloadSpec.from_dict(workload_payload)
    route = ExecutionRouteIdentity.from_dict(
        {
            "schema_version": "execution_route_identity@1",
            "route_id": "local.compute",
            "target_id": "local:host",
            "provider_id": "openzyme.process.podman",
            "inventory_generation": 1,
            "inventory_digest": digest,
            "qualification_digest": digest,
        }
    )
    observed: dict[str, object] = {}

    def fake_call(method: str, params: dict[str, object]) -> dict[str, str]:
        observed.update({"method": method, "params": params})
        return {
            "invocation_id": "invocation_1",
            "operation_id": "operation_1",
            "execution_id": "execution_1",
            "route_id": route.route_id,
            "workload_digest": workload.workload_digest,
        }

    monkeypatch.setattr(workload_sdk, "call", fake_call)
    invocation = workload_sdk.submit_workload(
        workload=workload,
        route=route,
        admission_identity={"session_id": "session_1", "authority_fence": 3},
    )

    assert observed["method"] == "execution.workload.submit"
    assert set(observed["params"]) == {
        "schema_version",
        "workload",
        "route_identity",
        "admission_identity",
    }
    assert invocation.route_id == "local.compute"
