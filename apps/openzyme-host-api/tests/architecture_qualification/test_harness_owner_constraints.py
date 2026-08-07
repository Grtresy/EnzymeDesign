from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from openzyme_host_api.harness_owner_constraints import (
    HarnessOwnerConstraintRegistryError,
)
from openzyme_host_api.harness_owner_constraints import (
    OWNER_CONSTRAINT_REGISTRY_RELATIVE_PATH,
)
from openzyme_host_api.harness_owner_constraints import (
    load_harness_owner_constraint_registry,
)
from openzyme_host_api.harness_owner_constraints import (
    validate_harness_owner_constraint_registry_bytes,
)

from .oracles import assert_strategy_neutrality_oracle
from .oracles import assert_world_fidelity_oracle


REPO_ROOT = Path(__file__).resolve().parents[4]
GENERIC_RUNTIME_SOURCES = (
    "packages/openzyme-core/src/openzyme_core/agent_runtime.py",
    "packages/openzyme-core/src/openzyme_core/harness.py",
    "packages/openzyme-core/src/openzyme_core/teammates.py",
    "packages/openzyme-runtime/src/openzyme_runtime/tooling.py",
)


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _neutral_observations() -> dict[str, dict[str, object]]:
    outcome = {
        "business_outcome": "positive-closure-eligible",
        "canonical_task_kinds": ["execution", "reporting", "research"],
        "composition_reachable": True,
        "external_effect_count": 1,
        "phase_veto_codes": [],
        "synthetic_reachability": False,
    }
    return {
        name: deepcopy(outcome)
        for name in (
            "baseline",
            "bounded_turn_split",
            "early_reporting_delegation",
            "inserted_read_and_prose",
            "reordered_safe_actions",
            "safe_rejection_followup",
        )
    }


def _faithful_observation() -> dict[str, object]:
    return {
        "automatic_recovery_count": 0,
        "earliest_typed_cause": "transport_connect_failed",
        "next_decision_visible_cause": "transport_connect_failed",
        "sealed_terminal_cause": "transport_connect_failed",
        "source_bound": True,
        "synthetic_fallback": False,
        "wrapper_chain": ["controlled_operation_failed", "runtime_command_failed"],
    }


def test_owner_registry_is_canonical_closed_and_source_resolved() -> None:
    registry = load_harness_owner_constraint_registry(REPO_ROOT)

    assert registry.source_path == REPO_ROOT / OWNER_CONSTRAINT_REGISTRY_RELATIVE_PATH
    assert registry.registry_digest.startswith("sha256:")
    constraints = registry.payload["constraints"]
    assert isinstance(constraints, list)
    assert {item["constraint_id"] for item in constraints} >= {
        "aox.offline-go",
        "aox.product-closure",
        "runtime.explicit-drain",
        "scientific.attempt-admission",
        "scientific.attempt-closure",
        "task.business-lifecycle",
        "task.delegation",
        "telemetry.reliability-shadow",
    }


def test_repository_guidance_uses_current_task_business_exit_owner() -> None:
    registry = load_harness_owner_constraint_registry(REPO_ROOT)
    constraints = registry.payload["constraints"]
    assert isinstance(constraints, list)
    task_lifecycle = next(
        item
        for item in constraints
        if item["constraint_id"] == "task.business-lifecycle"
    )
    assert task_lifecycle["owner_symbol"] == "finish_task"

    guidance_lines = [
        line
        for line in (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()
        if "task 业务终态必须由 agent 显式" in line
    ]
    assert len(guidance_lines) == 1
    assert "`task.finish`" in guidance_lines[0]
    assert "`task.update`" in guidance_lines[0]
    assert "只编辑普通字段和非终态" in guidance_lines[0]


def test_owner_registry_rejects_duplicate_owner_identity_and_dead_symbol() -> None:
    registry = load_harness_owner_constraint_registry(REPO_ROOT)
    payload = deepcopy(dict(registry.payload))
    constraints = deepcopy(payload["constraints"])
    assert isinstance(constraints, list)
    constraints[1]["constraint_id"] = constraints[0]["constraint_id"]
    payload["constraints"] = constraints
    with pytest.raises(HarnessOwnerConstraintRegistryError, match="unique"):
        validate_harness_owner_constraint_registry_bytes(
            _canonical(payload), repo_root=REPO_ROOT
        )

    payload = deepcopy(dict(registry.payload))
    constraints = deepcopy(payload["constraints"])
    assert isinstance(constraints, list)
    constraints[0]["owner_symbol"] = "deleted_owner_symbol"
    payload["constraints"] = constraints
    with pytest.raises(HarnessOwnerConstraintRegistryError, match="absent"):
        validate_harness_owner_constraint_registry_bytes(
            _canonical(payload), repo_root=REPO_ROOT
        )


def test_generic_runtime_has_no_aox_or_dispatch_policy_seam() -> None:
    forbidden = ("AoxFinalization", "aox_cutover", "tool_dispatch_precondition")
    for relative in GENERIC_RUNTIME_SOURCES:
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert all(token not in source for token in forbidden), relative


def test_qualification_and_telemetry_are_non_authoritative_dependencies() -> None:
    product_roots = (
        REPO_ROOT / "packages/openzyme-core/src/openzyme_core",
        REPO_ROOT / "packages/openzyme-runtime/src/openzyme_runtime",
    )
    for root in product_roots:
        for source_path in root.glob("*.py"):
            source = source_path.read_text(encoding="utf-8")
            assert "architecture_qualification" not in source

    telemetry = (
        REPO_ROOT
        / "packages/openzyme-runtime/src/openzyme_runtime/reliability.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "task.finish",
        "approval.grant",
        "automatic_rollover",
        "drive_until_terminal",
    ):
        assert forbidden not in telemetry


@pytest.mark.parametrize(
    "mutation",
    ("strategy_phase_veto", "synthetic_positive", "canonical_outcome_drift"),
)
def test_strategy_neutrality_red_oracle_rejects_policy_and_fake_reachability(
    mutation: str,
) -> None:
    observations = _neutral_observations()
    if mutation == "strategy_phase_veto":
        observations["early_reporting_delegation"]["phase_veto_codes"] = [
            "execution_not_completed"
        ]
    elif mutation == "synthetic_positive":
        observations["baseline"]["synthetic_reachability"] = True
    else:
        observations["reordered_safe_actions"]["business_outcome"] = "blocked"

    with pytest.raises(AssertionError):
        assert_strategy_neutrality_oracle(observations)


@pytest.mark.parametrize(
    "mutation",
    ("earliest_cause_overwrite", "automatic_recovery", "synthetic_fallback"),
)
def test_world_fidelity_red_oracle_rejects_causal_rewrite_and_recovery(
    mutation: str,
) -> None:
    observation = _faithful_observation()
    if mutation == "earliest_cause_overwrite":
        observation["sealed_terminal_cause"] = "runtime_drain_exhausted"
    elif mutation == "automatic_recovery":
        observation["automatic_recovery_count"] = 1
    else:
        observation["synthetic_fallback"] = True

    with pytest.raises(AssertionError):
        assert_world_fidelity_oracle(observation)
