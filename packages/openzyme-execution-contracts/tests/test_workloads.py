from __future__ import annotations

from copy import deepcopy

import pytest

from openzyme_execution_contracts import ExecutionRouteIdentity
from openzyme_execution_contracts import ExecutionResultReceipt
from openzyme_execution_contracts import ExecutionWireContractError
from openzyme_execution_contracts import ExecutionWireFailure
from openzyme_execution_contracts import ExecutionWorkloadSpec
from openzyme_execution_contracts import canonical_execution_wire_digest


DIGEST = "sha256:" + "1" * 64


def _workload_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "execution_workload_spec@1",
        "workload_id": "workload_1",
        "workload_contract": "enzymedesign.hmmer.search@1",
        "entry_point": "enzymedesign.hmmer.search@1",
        "argv": ["hmmbuild", "model.hmm", "alignment.fasta"],
        "cwd": "analysis/hmmer",
        "resource_policy_digest": DIGEST,
        "environment_policy_digest": DIGEST,
        "inputs": [
            {
                "revision_id": "revision_1",
                "commit": "a" * 40,
                "tree": "b" * 40,
                "path": "inputs/alignment.fasta",
                "content_digest": DIGEST,
            }
        ],
        "result_contract": {
            "contract_id": "enzymedesign.hmmer.result@1",
            "schema_digest": DIGEST,
            "result_root": "results/hmmer",
        },
        "capability_requirements": [
            {
                "capability_id": "software.hmmer",
                "version_spec": ">=3.3,<4",
                "operations": ["hmmbuild", "hmmsearch"],
            }
        ],
    }
    payload["workload_digest"] = canonical_execution_wire_digest(payload)
    return payload


def test_workload_is_closed_revision_bound_and_capability_described() -> None:
    workload = ExecutionWorkloadSpec.from_dict(_workload_payload())

    assert workload.cwd == "analysis/hmmer"
    assert workload.inputs[0].path == "inputs/alignment.fasta"
    assert workload.capability_requirements[0].capability_id == "software.hmmer"
    assert workload.to_dict() == _workload_payload()


@pytest.mark.parametrize(
    ("extra_field", "value"),
    [
        ("host_path", "/srv/openzyme/session"),
        ("remote_root", "/home/executor/session"),
        ("scheduler_job_id", "12345"),
        ("credential", "secret"),
        ("expected_outputs", ["result.csv"]),
    ],
)
def test_workload_rejects_implementation_and_host_leaks(
    extra_field: str,
    value: object,
) -> None:
    payload = _workload_payload()
    payload[extra_field] = value

    with pytest.raises(ExecutionWireContractError) as error:
        ExecutionWorkloadSpec.from_dict(payload)

    assert error.value.error_code == "execution_wire_fields_mismatch"


@pytest.mark.parametrize("path", ["/tmp/input", "../input", "a/../input", "./input"])
def test_workload_rejects_noncanonical_or_escaping_paths(path: str) -> None:
    payload = _workload_payload()
    inputs = deepcopy(payload["inputs"])
    assert isinstance(inputs, list)
    inputs[0]["path"] = path
    payload["inputs"] = inputs
    payload["workload_digest"] = canonical_execution_wire_digest(
        {key: value for key, value in payload.items() if key != "workload_digest"}
    )

    with pytest.raises(ExecutionWireContractError) as error:
        ExecutionWorkloadSpec.from_dict(payload)

    assert error.value.field == "inputs[].path"


def test_route_identity_binds_exact_inventory_generation_and_qualification() -> None:
    route = ExecutionRouteIdentity.from_dict(
        {
            "schema_version": "execution_route_identity@1",
            "route_id": "hpc.primary.hmmer",
            "target_id": "hpc:primary",
            "provider_id": "openzyme.hpc.slurm",
            "inventory_generation": 7,
            "inventory_digest": DIGEST,
            "qualification_digest": DIGEST,
        }
    )

    assert route.inventory_generation == 7


def test_failure_has_closed_effect_certainty_without_private_diagnostics() -> None:
    failure = ExecutionWireFailure.from_dict(
        {
            "schema_version": "execution_wire_failure@1",
            "error_code": "runner_dispatch_unknown",
            "phase": "dispatch",
            "effect_certainty": "dispatch_in_doubt",
            "retryable": False,
            "diagnostic_id": "diag_1",
        }
    )

    assert failure.effect_certainty == "dispatch_in_doubt"
    assert set(failure.to_dict()) == {
        "schema_version",
        "error_code",
        "phase",
        "effect_certainty",
        "retryable",
        "diagnostic_id",
    }


def test_result_receipt_is_terminal_opaque_and_path_free() -> None:
    result = ExecutionResultReceipt.from_dict(
        {
            "schema_version": "execution_result_receipt@1",
            "result_id": "result_1",
            "invocation_id": "invocation_1",
            "operation_id": "operation_1",
            "execution_id": "execution_1",
            "route_id": "hpc.primary.hmmer",
            "workload_digest": DIGEST,
            "state": "succeeded",
            "result_contract_digest": DIGEST,
            "result_revision_id": "revision_2",
            "result_digest": DIGEST,
            "terminal_receipt_digest": DIGEST,
        }
    )

    assert result.state == "succeeded"
    assert not ({"host_path", "remote_root", "scheduler_job_id"} & set(result.to_dict()))
