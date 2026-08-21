from __future__ import annotations

import importlib.metadata

from openzyme_research import ResearchEvidence
from openzyme_research import ResearchGap
from openzyme_research import ResearchProviderDescriptor
from openzyme_research import ResearchProviderKind
from openzyme_research import ResearchSourceRef
from openzyme_research import ResearchSummary
from openzyme_research import ResearchSummaryStatus
from openzyme_research import SourceRefKind


def test_research_contract_owner_does_not_depend_on_aggregate_domain() -> None:
    requirements = importlib.metadata.requires("openzyme-research") or []
    runtime_requirements = sorted(
        requirement for requirement in requirements if "extra ==" not in requirement
    )

    assert runtime_requirements == ["openzyme-contracts", "openzyme-extension-spi"]
    assert ResearchSummaryStatus.PARTIAL.is_terminal is True
    assert SourceRefKind.PAPER.value == "paper"


def test_research_records_preserve_existing_serialization_shape() -> None:
    summary = ResearchSummary(
        summary_id="summary-1",
        session_id="session-1",
        task_id="task-1",
        lane_id=None,
        invocation_id="invocation-1",
        status=ResearchSummaryStatus.COMPLETED,
        completion_reason="complete",
        research_brief="brief",
        summary="summary",
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
    )
    evidence = ResearchEvidence(
        evidence_id="evidence-1",
        session_id="session-1",
        task_id="task-1",
        lane_id=None,
        invocation_id="invocation-1",
        summary_id="summary-1",
        summary="evidence",
        query="query",
        created_at="2026-08-19T00:00:00+00:00",
    )
    source = ResearchSourceRef(
        source_ref_id="source-1",
        session_id="session-1",
        task_id="task-1",
        lane_id=None,
        invocation_id="invocation-1",
        evidence_id="evidence-1",
        title="source",
        locator="https://example.invalid/source",
        kind=SourceRefKind.WEB_PAGE,
        created_at="2026-08-19T00:00:00+00:00",
        authors=({"name": "Author"},),
    )
    gap = ResearchGap(
        gap_id="gap-1",
        session_id="session-1",
        task_id="task-1",
        lane_id=None,
        invocation_id="invocation-1",
        summary_id="summary-1",
        summary="gap",
        created_at="2026-08-19T00:00:00+00:00",
    )

    assert summary.to_dict()["status"] == "completed"
    assert evidence.to_dict()["query"] == "query"
    assert source.to_dict()["kind"] == "web_page"
    assert source.to_dict()["authors"] == [{"name": "Author"}]
    assert gap.to_dict()["summary"] == "gap"


def test_web_document_and_browser_adapters_share_one_provider_contract() -> None:
    descriptors = tuple(
        ResearchProviderDescriptor(
            adapter_component_id=f"example.research.{kind.value}",
            provider_id=f"example.research.{kind.value}",
            provider_kind=kind,
            contract_digest="sha256:" + str(index) * 64,
        )
        for index, kind in enumerate(ResearchProviderKind, start=1)
    )

    assert [descriptor.provider_kind.value for descriptor in descriptors] == [
        "web",
        "document",
        "browser",
    ]
    assert {descriptor.operations for descriptor in descriptors} == {
        ("dispatch", "reconcile")
    }
