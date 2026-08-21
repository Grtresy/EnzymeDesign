from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.model import (  # noqa: E402
    PYTEST_OBSERVATION_SCHEMA_ID,
    canonical_document_bytes,
    canonical_json_bytes,
    seal_document,
    sha256_digest,
)
from scripts.test_gate.shadow import (  # noqa: E402
    CollectionSnapshot,
    ShadowCollectionError,
    ShadowCoverageError,
    assert_source_stable,
    close_shadow_coverage,
    closed_non_live_environment,
    load_pytest_observation,
    load_qualification_scenario_collection,
)
from scripts.test_gate.source import SourceIdentity  # noqa: E402


def _snapshot(
    role: str,
    nodes: tuple[str, ...],
    *,
    invocation_id: str = "invocation-1",
    marker_overrides: dict[str, tuple[str, ...]] | None = None,
) -> CollectionSnapshot:
    marker_overrides = marker_overrides or {}
    collection = [
        {
            "node_id": node_id,
            "markers": list(marker_overrides.get(node_id, ())),
        }
        for node_id in nodes
    ]
    return CollectionSnapshot(
        invocation_id=invocation_id,
        role=role,
        nodes=nodes,
        markers=tuple(
            (node_id, marker_overrides.get(node_id, ())) for node_id in nodes
        ),
        digest=sha256_digest(canonical_json_bytes(collection)),
    )


def _closed_normal_coverage() -> dict[str, object]:
    return close_shadow_coverage(
        invocation_id="invocation-1",
        source_identity_digest="sha256:source",
        general=_snapshot("legacy_general", ("node-a", "node-b", "node-c")),
        qualification_harness=_snapshot(
            "qualification_harness",
            ("node-b",),
        ),
        qualification_scenarios=_snapshot(
            "qualification_scenario",
            ("node-c",),
        ),
        frontend_commands=(
            {"stage_id": "web_ui_test", "argv": ["npm", "test"]},
            {"stage_id": "web_ui_build", "argv": ["npm", "run", "build"]},
        ),
    )


def test_shadow_coverage_reports_legacy_duplicates_but_assigns_one_owner() -> None:
    document = _closed_normal_coverage()

    assert document["terminal_status"] == "pass"
    assert document["distinct_required_nodes"] == [
        "node-a",
        "node-b",
        "node-c",
    ]
    assert [
        item["node_id"] for item in document["structural_duplicates"]
    ] == ["node-b", "node-c"]
    assert len(document["legacy_execution_multiset"]) == 5
    owners = {
        item["node_id"]: item["owner"] for item in document["shadow_owners"]
    }
    assert owners == {
        "node-a": "general_non_live_pytest",
        "node-b": "architecture_qualification_premerge",
        "node-c": "architecture_qualification_premerge",
    }


def test_shadow_coverage_fails_for_missing_or_duplicate_owners() -> None:
    with pytest.raises(ShadowCoverageError, match="required nodes have no owner") as missing:
        close_shadow_coverage(
            invocation_id="invocation-1",
            source_identity_digest="sha256:source",
            general=_snapshot("legacy_general", ("node-a",)),
            qualification_harness=_snapshot("qualification_harness", ()),
            qualification_scenarios=_snapshot("qualification_scenario", ()),
            expected_required_nodes=("node-a", "node-missing"),
        )
    assert missing.value.document["terminal_status"] == "fail"

    with pytest.raises(
        ShadowCoverageError,
        match="qualification harness and scenario owners overlap",
    ):
        close_shadow_coverage(
            invocation_id="invocation-1",
            source_identity_digest="sha256:source",
            general=_snapshot("legacy_general", ("node-a",)),
            qualification_harness=_snapshot(
                "qualification_harness",
                ("node-a",),
            ),
            qualification_scenarios=_snapshot(
                "qualification_scenario",
                ("node-a",),
            ),
        )

    with pytest.raises(
        ShadowCoverageError,
        match="not present in the general non-live collection",
    ):
        close_shadow_coverage(
            invocation_id="invocation-1",
            source_identity_digest="sha256:source",
            general=_snapshot("legacy_general", ("node-a",)),
            qualification_harness=_snapshot(
                "qualification_harness",
                ("node-outside-g",),
            ),
            qualification_scenarios=_snapshot("qualification_scenario", ()),
        )


def test_shadow_coverage_fails_for_collection_drift_and_forbidden_markers() -> None:
    general = _snapshot(
        "legacy_general",
        ("node-a",),
        marker_overrides={"node-a": ("live_hpc",)},
    )
    with pytest.raises(ShadowCoverageError) as failure:
        close_shadow_coverage(
            invocation_id="invocation-1",
            source_identity_digest="sha256:source",
            general=general,
            qualification_harness=_snapshot("qualification_harness", ()),
            qualification_scenarios=_snapshot("qualification_scenario", ()),
            expected_collection_digests={"legacy_general": "sha256:prior"},
        )
    assert any("collection drifted" in reason for reason in failure.value.reasons)
    assert any("forbidden" in reason for reason in failure.value.reasons)
    assert failure.value.document["forbidden_nodes"] == [
        {
            "node_id": "node-a",
            "role": "legacy_general",
            "markers": ["live_hpc"],
        }
    ]


def test_shadow_coverage_rejects_prior_invocation_evidence() -> None:
    with pytest.raises(ShadowCoverageError, match="prior invocation"):
        close_shadow_coverage(
            invocation_id="invocation-1",
            source_identity_digest="sha256:source",
            general=_snapshot(
                "legacy_general",
                ("node-a",),
                invocation_id="prior-invocation",
            ),
            qualification_harness=_snapshot("qualification_harness", ()),
            qualification_scenarios=_snapshot("qualification_scenario", ()),
        )


def test_observation_loader_rejects_malformed_and_prior_documents(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_bytes(b"{}\n")
    with pytest.raises(ShadowCollectionError, match="invalid pytest observation"):
        load_pytest_observation(malformed)

    document = seal_document(
        PYTEST_OBSERVATION_SCHEMA_ID,
        {
            "invocation_id": "prior",
            "role": "legacy_general",
            "mode": "collect",
            "pytest_argv": ["pytest", "--collect-only"],
            "cwd": "/tmp",
            "collection": [{"node_id": "node-a", "markers": []}],
            "deselected": [],
            "node_results": [],
            "session_exit_code": 0,
            "started_monotonic_ns": 1,
            "duration_ns": 2,
        },
    )
    prior = tmp_path / "prior.json"
    prior.write_bytes(canonical_document_bytes(document))
    with pytest.raises(ShadowCollectionError, match="prior or different"):
        load_pytest_observation(
            prior,
            expected_invocation_id="current",
        )


def test_qualification_collection_closes_against_registry(tmp_path: Path) -> None:
    registry = {
        "required_scenario_ids": ["scenario-a", "scenario-b"],
        "scenarios": [
            {
                "family": "family-a",
                "scenario_id": "scenario-a",
                "selections": ["full", "premerge_subset"],
                "source_files": ["tests/test_a.py"],
                "test_selector": "tests/test_a.py::test_a",
            },
            {
                "family": "family-b",
                "scenario_id": "scenario-b",
                "selections": ["full"],
                "source_files": ["tests/test_b.py"],
                "test_selector": "tests/test_b.py::test_b",
            },
        ],
        "document_ref": "docs/OpenZyme架构设计.md",
        "schema_id": "openzyme_v3_architecture_invariant_registry@3",
    }
    collection = {
        "scenarios": [
            {
                "family": "family-a",
                "node_id": "tests/test_a.py::test_a",
                "scenario_id": "scenario-a",
                "selections": ["full", "premerge_subset"],
                "source_file": "tests/test_a.py",
            },
            {
                "family": "family-b",
                "node_id": "tests/test_b.py::test_b",
                "scenario_id": "scenario-b",
                "selections": ["full"],
                "source_file": "tests/test_b.py",
            },
        ],
        "schema_id": "openzyme_v3_architecture_pytest_collection@1",
    }
    registry_path = tmp_path / "registry.json"
    collection_path = tmp_path / "collection.json"
    registry_path.write_bytes(
        json.dumps(
            registry,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    collection_path.write_bytes(canonical_json_bytes(collection) + b"\n")

    snapshot = load_qualification_scenario_collection(
        collection_path,
        registry_path=registry_path,
        invocation_id="invocation-1",
    )
    assert snapshot.nodes == ("tests/test_a.py::test_a",)
    assert snapshot.role == "qualification_scenario"


def test_source_recheck_and_environment_policy_fail_closed() -> None:
    before = SourceIdentity(
        commit="a" * 40,
        tracked_diff_digest="sha256:one",
        tracked_dirty_paths=(),
        relevant_untracked_sources=(),
        configurations=(),
        locks=(),
        toolchains=(),
    )
    assert_source_stable(before, before)
    with pytest.raises(ShadowCollectionError, match="source identity drifted"):
        assert_source_stable(
            before,
            replace(before, tracked_diff_digest="sha256:two"),
        )

    environment = closed_non_live_environment(
        {
            "PATH": "/bin",
            "OPENAI_API_KEY": "secret",
            "SSH_AUTH_SOCK": "/tmp/agent",
            "OPENZYME_RUN_LIVE": "1",
            "PYTEST_ADDOPTS": "-m live_hpc",
        },
        qualification=False,
    )
    assert environment["PATH"] == "/bin"
    assert environment["OPENZYME_LOAD_ENV_FILES"] == "0"
    assert "OPENAI_API_KEY" not in environment
    assert "SSH_AUTH_SOCK" not in environment
    assert "OPENZYME_RUN_LIVE" not in environment
    assert "PYTEST_ADDOPTS" not in environment
    assert "OPENZYME_ARCHITECTURE_QUALIFICATION" not in environment
