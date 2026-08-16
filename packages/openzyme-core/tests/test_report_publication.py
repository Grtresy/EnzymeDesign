from types import SimpleNamespace

import pytest

from openzyme_core import is_published_report_link
from openzyme_core import is_published_report_status


@pytest.mark.parametrize("status", ["ready", "published"])
def test_published_report_link_accepts_both_success_terminal_statuses(
    status: str,
) -> None:
    report = SimpleNamespace(
        report_id="report_001",
        session_id="sess_001",
        task_id="task_report",
        status=SimpleNamespace(value=status),
        content_ref_id="doc_001",
        report_version=1,
    )
    draft = SimpleNamespace(
        session_id="sess_001",
        task_id="task_report",
        status=SimpleNamespace(value="published"),
        published_report_id="report_001",
        content_ref="doc_001",
    )

    assert is_published_report_status(report) is True
    assert is_published_report_link(report, draft, task_id="task_report") is True


def test_published_report_link_rejects_cross_identity_link() -> None:
    report = {
        "report_id": "report_001",
        "session_id": "sess_001",
        "task_id": "task_report",
        "status": "published",
    }
    draft = {
        "session_id": "sess_other",
        "task_id": "task_report",
        "status": "published",
        "published_report_id": "report_001",
        "content_ref": "doc_001",
    }

    assert is_published_report_link(report, draft) is False
