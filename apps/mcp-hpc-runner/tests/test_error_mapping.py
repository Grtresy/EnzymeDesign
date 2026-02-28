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
