from __future__ import annotations

from openzyme_host_api.architecture_qualification import REQUIRED_FAMILIES
from openzyme_host_api.architecture_qualification import load_invariant_registry

from .conftest import REPO_ROOT


def test_final_file_architecture_registry_closes_required_families() -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    scenarios = registry.payload["scenarios"]
    invariants = registry.payload["invariants"]
    assert isinstance(scenarios, list) and len(scenarios) >= len(REQUIRED_FAMILIES)
    assert isinstance(invariants, list) and {
        item["family"] for item in invariants
    } == set(REQUIRED_FAMILIES)
    assert {
        "boundary-scale.public-diagnostic-bounded-work",
        "supervisor-progress.semantic-progress-only",
    } <= {item["scenario_id"] for item in scenarios}
