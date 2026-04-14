from __future__ import annotations

import signal
from dataclasses import replace

import pytest

from openzyme_domain import Episode
from openzyme_graph.design import build_phase_c_design_graph
from openzyme_host_api.foundation import apply_live_llm_test_budget
from openzyme_host_api.foundation import build_configured_foundation
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import get_settings


pytestmark = [pytest.mark.integration, pytest.mark.live_llm, pytest.mark.live_tavily]


class LiveDesignResearchTimeoutError(TimeoutError):
    """Raised when the live design->research test exceeds its timeout budget."""


class _AlarmTimeout:
    def __init__(self, seconds: int) -> None:
        self._seconds = seconds
        self._previous_handler = None

    def __enter__(self) -> "_AlarmTimeout":
        self._previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self._handle_timeout)
        signal.alarm(self._seconds)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        signal.alarm(0)
        if self._previous_handler is not None:
            signal.signal(signal.SIGALRM, self._previous_handler)
        return None

    @staticmethod
    def _handle_timeout(signum: int, frame: object | None) -> None:
        del signum, frame
        raise LiveDesignResearchTimeoutError(
            "live design->research test exceeded its local timeout budget."
        )


def test_live_design_calls_deep_research_and_persists_results(tmp_path) -> None:
    settings = apply_live_llm_test_budget(get_settings())
    tuned_settings = replace(
        settings,
        research=replace(
            settings.research,
            allow_clarification=False,
            max_research_iterations=1,
            max_react_tool_calls=1,
            max_concurrent_research_units=1,
        ),
    )
    foundation = build_configured_foundation(
        sqlite_db_path=tmp_path / "live-design-research.sqlite3",
        settings=tuned_settings,
    )
    foundation.repositories.episodes.save(
        Episode.create(
            episode_id="ep_live_design_research",
            project_id="proj_001",
            objective="Find literature-backed thermostability strategies for enzyme engineering and use them to draft design candidates.",
        )
    )

    facade = GraphRuntimeFacade(foundation)
    config = facade.build_episode_graph_config("ep_live_design_research")

    with _AlarmTimeout(240):
        with facade.compile_graph(build_phase_c_design_graph) as graph:
            result = graph.invoke(
                {
                    "episode_id": "ep_live_design_research",
                    "project_id": "proj_001",
                    "objective": "Find literature-backed thermostability strategies for enzyme engineering and use them to draft design candidates.",
                },
                config,
            )

    assert result["__interrupt__"][0].value["type"] == "approval"

    research_summary = foundation.repositories.research_summaries.get_by_episode(
        "ep_live_design_research"
    )
    evidence_records = foundation.repositories.evidence_records.list_by_episode(
        "ep_live_design_research"
    )
    source_refs = foundation.repositories.source_refs.list_by_episode("ep_live_design_research")
    candidates = foundation.repositories.candidates.list_by_episode("ep_live_design_research")
    decisions = foundation.repositories.decisions.list_by_episode("ep_live_design_research")
    research_decisions = [decision for decision in decisions if decision.phase == "research"]
    design_collect_research = [
        decision
        for decision in decisions
        if decision.phase == "design" and decision.action_kind == "collect_research"
    ]

    print("\n=== Live Design -> Research Snapshot ===", flush=True)
    if design_collect_research:
        latest_collect = design_collect_research[-1]
        observation = latest_collect.observation_payload or {}
        tool_result = observation.get("tool_result") or {}
        print(f"collect_research status: {observation.get('status')}", flush=True)
        print(f"collect_research completion_reason: {observation.get('completion_reason')}", flush=True)
        print(f"research_brief: {tool_result.get('research_brief')}", flush=True)
    if research_summary is not None:
        print(f"research_summary: {research_summary.summary}", flush=True)

    print("\nTop evidence:", flush=True)
    for index, evidence in enumerate(evidence_records[:3], start=1):
        linked_sources = [
            source
            for source in source_refs
            if source.evidence_id == evidence.evidence_id
        ]
        print(f"{index}. query={evidence.query}", flush=True)
        print(f"   summary={evidence.summary}", flush=True)
        for source in linked_sources[:2]:
            print(f"   source={source.title} | {source.locator}", flush=True)

    print("\nRecent research turns:", flush=True)
    for decision in research_decisions[-5:]:
        print(
            f"- turn={decision.turn_index} action={decision.action_kind} status={decision.status.value} "
            f"summary={decision.summary}",
            flush=True,
        )

    print("\nDrafted candidates:", flush=True)
    for candidate in candidates[:3]:
        print(f"- {candidate.candidate_id}: {candidate.title}", flush=True)
        print(f"  summary={candidate.summary}", flush=True)
        print(f"  evidence_ids={list(candidate.supporting_evidence_ids)}", flush=True)

    assert research_summary is not None
    assert research_summary.summary
    assert evidence_records
    assert source_refs
    assert any(
        decision.phase == "design" and decision.action_kind == "collect_research"
        for decision in decisions
    )
    assert any(decision.phase == "research" for decision in decisions)
    assert any(record.query for record in evidence_records)
    assert any(record.summary for record in evidence_records)
    assert any(source.locator.startswith("http") for source in source_refs)
    assert candidates
    assert any(candidate.supporting_evidence_ids for candidate in candidates)
    assert any(
        "thermostab" in record.summary.lower() or "enzyme" in record.summary.lower()
        for record in evidence_records
    )
