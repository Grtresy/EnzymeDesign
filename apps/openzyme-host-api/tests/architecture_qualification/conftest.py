from __future__ import annotations

import os
import hashlib
from pathlib import Path
import time
from typing import Any

import pytest

from openzyme_host_api.architecture_qualification import canonical_json_document_bytes

from .collection import SCENARIO_MARKER
from .collection import collect_qualification_scenarios
from .collection import collection_payload
from .execution_evidence import execution_evidence_snapshot


REPO_ROOT = Path(__file__).resolve().parents[4]
_COLLECTION_OUTPUT_ENV = "OPENZYME_ARCHITECTURE_COLLECTION_OUTPUT"
_EXECUTION_OUTPUT_ENV = "OPENZYME_ARCHITECTURE_EXECUTION_OUTPUT"
_EXECUTION_SCHEMA_ID = "openzyme_v3_architecture_pytest_execution@1"
_MAINLINE_NODE_OUTPUT_ENV = "OPENZYME_MAINLINE_QUALIFICATION_NODE_OUTPUT"
_MAINLINE_NODE_SCHEMA_ID = "openzyme_v3_mainline_qualification_pytest@1"
_EXECUTION_SCENARIOS: dict[str, dict[str, object]] = {}
_MAINLINE_NODES: dict[str, dict[str, object]] = {}
_MAINLINE_NODE_STARTED: dict[str, int] = {}
_MAINLINE_NODE_DURATION: dict[str, int] = {}


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _report_phase(report: Any) -> dict[str, object]:
    longrepr = "" if report.passed else str(report.longrepr)
    return {
        "duration_milliseconds": max(0, round(float(report.duration) * 1000)),
        "failure_digest": None if not longrepr else _sha256(longrepr.encode("utf-8")),
        "outcome": str(report.outcome),
        "phase": str(report.when),
        "was_xfail": bool(getattr(report, "wasxfail", False)),
    }


def _pytest_outcome(phases: list[dict[str, object]]) -> str:
    for phase in phases:
        if phase["was_xfail"] and phase["outcome"] == "passed":
            return "xpass"
        if phase["was_xfail"]:
            return "xfail"
    if any(
        phase["phase"] in {"setup", "teardown"} and phase["outcome"] == "failed"
        for phase in phases
    ):
        return "error"
    if any(phase["outcome"] == "skipped" for phase in phases):
        return "skip"
    if any(
        phase["phase"] == "call" and phase["outcome"] == "failed" for phase in phases
    ):
        return "fail"
    if any(
        phase["phase"] == "call" and phase["outcome"] == "passed" for phase in phases
    ):
        return "pass"
    return "error"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{SCENARIO_MARKER}(scenario_id, family, selections): closed V3 architecture scenario",
    )


def pytest_collection_finish(session: pytest.Session) -> None:
    target_text = os.environ.get(_COLLECTION_OUTPUT_ENV)
    scenarios = collect_qualification_scenarios(
        session.items,
        repo_root=REPO_ROOT,
    )
    if target_text is not None:
        target = Path(target_text)
        if not target.is_absolute():
            raise pytest.UsageError(
                f"{_COLLECTION_OUTPUT_ENV} must be an absolute path"
            )
        content = canonical_json_document_bytes(collection_payload(scenarios))
        try:
            with target.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise pytest.UsageError(
                "architecture collection output already exists"
            ) from exc

    if os.environ.get(_EXECUTION_OUTPUT_ENV) is not None:
        _EXECUTION_SCENARIOS.clear()
        for scenario in scenarios:
            _EXECUTION_SCENARIOS[scenario.node_id] = {
                "family": scenario.family,
                "phases": [],
                "scenario_id": scenario.scenario_id,
                "test_selector": scenario.node_id,
            }
    if os.environ.get(_MAINLINE_NODE_OUTPUT_ENV) is not None:
        _MAINLINE_NODES.clear()
        _MAINLINE_NODE_STARTED.clear()
        _MAINLINE_NODE_DURATION.clear()
        for item in session.items:
            node_id = str(item.nodeid)
            if node_id in _MAINLINE_NODES:
                raise pytest.UsageError(
                    f"mainline qualification contains duplicate node id {node_id!r}"
                )
            _MAINLINE_NODES[node_id] = {
                "markers": sorted({marker.name for marker in item.iter_markers()}),
                "phases": [],
            }


def pytest_runtest_logstart(
    nodeid: str,
    location: tuple[str, int | None, str],
) -> None:
    del location
    if nodeid in _MAINLINE_NODES:
        _MAINLINE_NODE_STARTED[nodeid] = time.monotonic_ns()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    scenario = _EXECUTION_SCENARIOS.get(str(report.nodeid))
    if scenario is not None:
        phases = scenario["phases"]
        if not isinstance(phases, list):
            raise AssertionError("qualification execution phases lost list identity")
        phases.append(_report_phase(report))
    mainline = _MAINLINE_NODES.get(str(report.nodeid))
    if mainline is not None:
        mainline_phases = mainline["phases"]
        if not isinstance(mainline_phases, list):
            raise AssertionError("mainline qualification phases lost list identity")
        mainline_phases.append(_report_phase(report))


def pytest_runtest_logfinish(
    nodeid: str,
    location: tuple[str, int | None, str],
) -> None:
    del location
    started = _MAINLINE_NODE_STARTED.get(nodeid)
    if started is not None:
        _MAINLINE_NODE_DURATION[nodeid] = max(
            0,
            time.monotonic_ns() - started,
        )


def pytest_sessionfinish(session: pytest.Session) -> None:
    del session
    target_text = os.environ.get(_EXECUTION_OUTPUT_ENV)
    if target_text is not None:
        target = Path(target_text)
        if not target.is_absolute():
            raise pytest.UsageError(f"{_EXECUTION_OUTPUT_ENV} must be an absolute path")
        evidence = execution_evidence_snapshot()
        records: list[dict[str, object]] = []
        for raw in sorted(
            _EXECUTION_SCENARIOS.values(),
            key=lambda item: str(item["scenario_id"]),
        ):
            phases = raw["phases"]
            if not isinstance(phases, list):
                raise AssertionError(
                    "qualification execution phases lost list identity"
                )
            records.append(
                {
                    "duration_milliseconds": sum(
                        int(phase["duration_milliseconds"]) for phase in phases
                    ),
                    "effect_ledger_digests": evidence["effect_ledger_digests"],
                    "external_effects_real": evidence["external_effects_real"],
                    "failure_digests": [
                        phase["failure_digest"]
                        for phase in phases
                        if phase["failure_digest"] is not None
                    ],
                    "family": raw["family"],
                    "observation_digests": evidence["observation_digests"],
                    "observed_p0_trigger_ids": evidence["observed_p0_trigger_ids"],
                    "pytest_outcome": _pytest_outcome(phases),
                    "scenario_id": raw["scenario_id"],
                    "test_selector": raw["test_selector"],
                }
            )
            records[-1]["failure_digests"] = sorted(set(records[-1]["failure_digests"]))
        payload = {"records": records, "schema_id": _EXECUTION_SCHEMA_ID}
        content = canonical_json_document_bytes(payload)
        try:
            with target.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise pytest.UsageError(
                "architecture execution output already exists"
            ) from exc

    mainline_target_text = os.environ.get(_MAINLINE_NODE_OUTPUT_ENV)
    if mainline_target_text is None:
        return
    mainline_target = Path(mainline_target_text)
    if not mainline_target.is_absolute():
        raise pytest.UsageError(f"{_MAINLINE_NODE_OUTPUT_ENV} must be an absolute path")
    node_records: list[dict[str, object]] = []
    for node_id in sorted(_MAINLINE_NODES):
        raw = _MAINLINE_NODES[node_id]
        phases = raw["phases"]
        markers = raw["markers"]
        if not isinstance(phases, list) or not isinstance(markers, list):
            raise AssertionError(
                "mainline qualification node evidence lost list identity"
            )
        node_records.append(
            {
                "duration_ns": _MAINLINE_NODE_DURATION.get(
                    node_id,
                    sum(
                        int(phase["duration_milliseconds"]) * 1_000_000
                        for phase in phases
                    ),
                ),
                "markers": markers,
                "node_id": node_id,
                "outcome": _pytest_outcome(phases),
                "phases": phases,
            }
        )
    mainline_content = canonical_json_document_bytes(
        {
            "nodes": node_records,
            "schema_id": _MAINLINE_NODE_SCHEMA_ID,
        }
    )
    try:
        with mainline_target.open("xb") as handle:
            handle.write(mainline_content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise pytest.UsageError(
            "mainline qualification node output already exists"
        ) from exc


@pytest.fixture
def architecture_scenario_marker_name() -> str:
    return SCENARIO_MARKER


def pytest_report_header(config: pytest.Config) -> str | None:
    del config
    if os.environ.get(_COLLECTION_OUTPUT_ENV) is None:
        return None
    return "OpenZyme V3 architecture collection closure enabled"


__all__: tuple[str, ...] = ()
