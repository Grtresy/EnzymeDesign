from __future__ import annotations

from openzyme_host_api.tracing import build_trace_metadata
from openzyme_host_api.tracing import build_trace_tags


def test_trace_helpers_include_session_scoped_metadata() -> None:
    assert build_trace_tags(
        action="resolve_v3_approval",
        project_id="proj_001",
        session_id="sess_001",
        phase="runtime",
        approval_id="approval_001",
    ) == [
        "action:resolve_v3_approval",
        "project:proj_001",
        "session:sess_001",
        "phase:runtime",
        "approval:approval_001",
    ]
    assert build_trace_metadata(
        action="post_v3_message",
        project_id="proj_001",
        session_id="sess_001",
        phase="runtime",
        request_method="POST",
        request_path="/v3/sessions/sess_001/messages",
    ) == {
        "action": "post_v3_message",
        "project_id": "proj_001",
        "session_id": "sess_001",
        "phase": "runtime",
        "request_method": "POST",
        "request_path": "/v3/sessions/sess_001/messages",
    }
