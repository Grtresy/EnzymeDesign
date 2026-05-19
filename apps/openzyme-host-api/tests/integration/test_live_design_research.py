from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_runtime.live_testing import LiveStageTimeout
from openzyme_runtime.live_testing import derive_live_graph_timeout_seconds
from openzyme_runtime.live_testing import log_live_phase
from openzyme_domain import Episode
from openzyme_graph.design import build_phase_c_design_graph
from openzyme_host_api.foundation import apply_live_llm_test_budget
from openzyme_host_api.foundation import build_configured_foundation
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import get_settings


pytestmark = [pytest.mark.integration, pytest.mark.live_llm, pytest.mark.live_tavily]


class LiveDesignResearchTimeoutError(TimeoutError):
    """Raised when the live design->research test exceeds its timeout budget."""


def test_live_design_records_deep_research_contract(tmp_path) -> None:
    log_live_phase("loading live settings for design->research")
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
    log_live_phase("building configured foundation for live design->research")
    foundation = build_configured_foundation(
        sqlite_db_path=tmp_path / "live-design-research.sqlite3",
        settings=tuned_settings,
    )
    log_live_phase("saving live design->research episode")
    foundation.repositories.episodes.save(
        Episode.create(
            episode_id="ep_live_design_research",
            project_id="proj_001",
            objective="Find literature-backed thermostability strategies for enzyme engineering and curate design artifacts.",
        )
    )

    facade = GraphRuntimeFacade(foundation)
    config = facade.build_episode_graph_config("ep_live_design_research")
    graph_timeout_seconds = derive_live_graph_timeout_seconds(
        llm_timeout_seconds=tuned_settings.llm.timeout,
        structured_attempts=tuned_settings.llm.structured_output_max_attempts,
        tavily_timeout_seconds=tuned_settings.research.tavily_timeout_seconds,
        expected_llm_call_budget=8,
        expected_tavily_budget=2,
        buffer_seconds=60,
    )
    log_live_phase(
        "derived live design graph timeout: "
        f"{graph_timeout_seconds}s "
        f"(llm_timeout={tuned_settings.llm.timeout}, "
        f"structured_attempts={tuned_settings.llm.structured_output_max_attempts}, "
        f"tavily_timeout={tuned_settings.research.tavily_timeout_seconds})"
    )

    with LiveStageTimeout(
        "compiling and invoking graph.invoke design research",
        graph_timeout_seconds,
        timeout_type=LiveDesignResearchTimeoutError,
    ):
        log_live_phase("compiling live design graph")
        with facade.compile_graph(build_phase_c_design_graph) as graph:
            log_live_phase("invoking live design graph")
            result = graph.invoke(
                {
                    "episode_id": "ep_live_design_research",
                    "project_id": "proj_001",
                    "objective": "Find literature-backed thermostability strategies for enzyme engineering and curate design artifacts.",
                },
                config,
            )

    assert result["status"] == "completed"
    assert result["recommended_next_phase"] in {"execution", "report_review"}
    if result["recommended_next_phase"] == "execution":
        assert result["execution_handoff"]["recommended_next_phase"] == "execution"
        assert result["execution_handoff"]["required_artifact_ids"]
    else:
        assert result["design_handoff"]["recommended_next_phase"] == "report_review"

    log_live_phase("checking persisted live research and design artifacts")
    research_summary = foundation.repositories.research_summaries.get_by_episode(
        "ep_live_design_research"
    )
    evidence_records = foundation.repositories.evidence_records.list_by_episode(
        "ep_live_design_research"
    )
    source_refs = foundation.repositories.source_refs.list_by_episode("ep_live_design_research")
    artifacts = foundation.repositories.artifact_records.list_by_episode("ep_live_design_research")
    design_artifacts = [
        artifact
        for artifact in artifacts
        if "design-option" in artifact.tags
        or artifact.metadata
        and artifact.metadata.get("semantic_type") == "design_option"
    ]
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

    print("\nCurated design artifacts:", flush=True)
    for artifact in design_artifacts[:3]:
        print(f"- {artifact.artifact_id}: {artifact.title}", flush=True)
        print(f"  summary={artifact.description}", flush=True)
        print(f"  metadata={artifact.metadata}", flush=True)

    assert design_collect_research
    assert research_decisions

    latest_collect = design_collect_research[-1]
    observation = latest_collect.observation_payload or {}
    assert observation.get("status") in {"completed", "partial"}

    has_persisted_research_output = bool(
        (research_summary is not None and research_summary.summary)
        or evidence_records
        or source_refs
    )
    assert has_persisted_research_output
    assert research_summary is not None
    assert research_summary.summary
    assert evidence_records
    assert any(record.query for record in evidence_records)
    assert any(record.summary for record in evidence_records)
    assert source_refs
    assert any(source.locator for source in source_refs)
