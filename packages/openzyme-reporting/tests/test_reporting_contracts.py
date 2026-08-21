from __future__ import annotations

import importlib.metadata

from openzyme_reporting import SessionReportDraftRecord
from openzyme_reporting import SessionReportDraftStatus
from openzyme_reporting import SessionReportRecord
from openzyme_reporting import SessionReportStatus


def test_reporting_wheel_owns_report_contracts_without_implementation_deps() -> None:
    requirements = importlib.metadata.requires("openzyme-reporting") or []
    runtime_requirements = sorted(
        requirement for requirement in requirements if "extra ==" not in requirement
    )

    assert runtime_requirements == ["openzyme-contracts", "openzyme-extension-spi"]
    assert SessionReportStatus.READY.is_terminal is True
    assert SessionReportDraftStatus.READY.is_terminal is False


def test_report_records_preserve_existing_serialization_shape() -> None:
    report = SessionReportRecord(
        report_id="report-1",
        session_id="session-1",
        task_id="task-1",
        lane_id=None,
        invocation_id=None,
        run_id=None,
        status=SessionReportStatus.READY,
        title="结果",
        summary="摘要",
        stage_summary="ready",
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
    )
    draft = SessionReportDraftRecord(
        draft_id="draft-1",
        session_id="session-1",
        task_id="task-1",
        owner_agent_id="agent-1",
        status=SessionReportDraftStatus.IN_REVIEW,
        title="草稿",
        summary="摘要",
        content_ref="ref-1",
        published_report_id=None,
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
    )

    assert report.to_dict()["status"] == "ready"
    assert report.to_dict()["report_version"] == 1
    assert draft.to_dict()["status"] == "in_review"
    assert draft.to_dict()["content_ref"] == "ref-1"
