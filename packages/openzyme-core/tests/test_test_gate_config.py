from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.config import (  # noqa: E402
    CONFIG_SCHEMA_ID,
    RESOURCE_CLASSES,
    ConfigError,
    load_config,
)

CONFIG_PATH = REPOSITORY_ROOT / "scripts" / "test-gate.toml"


def test_config_closes_profiles_deadlines_environments_and_resources() -> None:
    config = load_config(CONFIG_PATH)

    assert config.schema_id == CONFIG_SCHEMA_ID
    assert config.digest.startswith("sha256:")
    assert config.worker_hard_max == 4
    assert config.supported_profiles == (
        "focused_diagnostic",
        "affected_scope_diagnostic",
        "mainline_authoritative",
    )
    assert config.resource_policy.closed_classes == RESOURCE_CLASSES
    assert config.resource_policy.default_class == "serial_unknown"
    assert config.pytest_contract.marker_expression == (
        "not integration and not live_llm and not live_tavily and not live_hpc "
        "and not live_e2e and not quality_eval"
    )
    assert config.pytest_contract.architecture_scenario_marker == (
        "architecture_qualification_scenario"
    )
    assert set(config.pytest_contract.allowed_non_live_markers) == {
        "architecture_qualification_scenario",
        "parametrize",
        "podman",
        "skip",
        "skipif",
        "slow",
        "xfail",
    }
    assert all(stage.deadline_seconds > 0 for stage in config.stages)
    assert all(stage.environment_policy for stage in config.stages)
    assert all(stage.resource_class in RESOURCE_CLASSES for stage in config.stages)

    focused = config.profile("focused_diagnostic")
    affected = config.profile("affected_scope_diagnostic")
    mainline = config.profile("mainline_authoritative")
    assert (
        focused.authoritative,
        focused.admission_eligible,
        focused.live_eligible,
    ) == (False, False, False)
    assert (
        affected.authoritative,
        affected.admission_eligible,
        affected.live_eligible,
    ) == (False, False, False)
    assert (
        mainline.authoritative,
        mainline.admission_eligible,
        mainline.live_eligible,
    ) == (True, False, False)


def test_config_rejects_unknown_fields_and_worker_counts_above_four(
    tmp_path: Path,
) -> None:
    original = CONFIG_PATH.read_text(encoding="utf-8")
    unknown = tmp_path / "unknown.toml"
    unknown.write_text(f"unexpected = true\n{original}", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown fields"):
        load_config(unknown)

    excessive_workers = tmp_path / "workers.toml"
    excessive_workers.write_text(
        original.replace("worker_hard_max = 4", "worker_hard_max = 5", 1),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="must not exceed 4"):
        load_config(excessive_workers)


def test_config_rejects_any_authority_upgrade_for_diagnostics(
    tmp_path: Path,
) -> None:
    original = CONFIG_PATH.read_text(encoding="utf-8")
    upgraded = tmp_path / "upgraded.toml"
    marker = (
        'id = "focused_diagnostic"\n'
        "stage_ids = []\n"
        "authoritative = false"
    )
    upgraded.write_text(
        original.replace(
            marker,
            marker.replace("authoritative = false", "authoritative = true"),
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="permanently non-authoritative"):
        load_config(upgraded)
