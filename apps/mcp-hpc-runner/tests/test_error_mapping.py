from __future__ import annotations

from mcp_hpc_runner.errors import FailureMapper
from mcp_hpc_runner.models import FailureSignature


def test_custom_failure_signature_has_priority() -> None:
    mapper = FailureMapper()
    mapped = mapper.map_error(
        "fatal: wrapper unavailable",
        [FailureSignature("wrapper unavailable", "WRAPPER_MISSING")],
    )
    assert mapped is not None
    assert mapped.code == "WRAPPER_MISSING"


def test_default_failure_signature_mapping() -> None:
    mapper = FailureMapper()
    mapped = mapper.map_error("CUDA out of memory while running model")
    assert mapped is not None
    assert mapped.code == "CUDA_OOM"


def test_ssh_connection_timeout_is_distinct_from_payload_failure() -> None:
    mapper = FailureMapper()
    mapped = mapper.map_error(
        "Connection to 192.0.2.10 port 22222 timed out"
    )
    assert mapped is not None
    assert mapped.code == "SSH_CONNECTION_TIMEOUT"


def test_other_ssh_connection_failures_remain_transport_failures() -> None:
    mapper = FailureMapper()
    mapped = mapper.map_error(
        "ssh: connect to host runner.invalid port 22: Connection refused"
    )
    assert mapped is not None
    assert mapped.code == "SSH_CONNECTION_FAILED"
