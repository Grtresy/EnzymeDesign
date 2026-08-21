from __future__ import annotations

import asyncio

from openzyme_contracts import require_digest
from openzyme_host_api.evals import run_eval


def test_host_v2_eval_is_exact_and_non_live() -> None:
    result = asyncio.run(run_eval())

    assert result["status"] == "passed"
    assert result["public_contract"] == "file_workspace_public@2"
    for field_name in (
        "public_contract_digest",
        "release_digest",
        "extension_bundle_digest",
        "declared_tool_catalog_digest",
        "capability_binding_digest",
        "affordance_snapshot_digest",
        "workspace_backend_digest",
    ):
        require_digest(str(result[field_name]), field_name=field_name)
    assert result["bootstrap_count"] == 1
    assert result["accepted_mutation_count"] == 1
    assert result["stale_mutation_rejected_before_dispatch"] is True
    assert result["external_effect_performed"] is False
    assert result["fallback_performed"] is False
