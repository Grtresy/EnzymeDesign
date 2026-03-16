from __future__ import annotations

from html import escape
import json
import os
from pathlib import Path
from typing import Any

from enzyme_host_runtime import HostRuntime
from enzyme_host_runtime import WorkspaceError
from mcp_project_memory.store import StaleStateError
from fastapi import FastAPI
from fastapi import Form
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import HTMLResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import RedirectResponse


def create_app(
    *,
    project_root: Path | None = None,
    runtime: HostRuntime | None = None,
) -> FastAPI:
    app = FastAPI(title="OpenZyme Web Host")
    bound_root = _resolve_project_root(project_root)
    app.state.runtime = runtime or HostRuntime()
    app.state.project_root = bound_root

    @app.get("/", response_class=HTMLResponse)
    def index(
        run_id: str | None = Query(default=None),
        stale: int = Query(default=0),
    ) -> str:
        return _render_index(app.state.runtime, app.state.project_root, run_id=run_id, stale=bool(stale))

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        return app.state.runtime.get_status(app.state.project_root).to_dict()

    @app.get("/api/capabilities")
    def api_capabilities() -> list[dict[str, Any]]:
        return app.state.runtime.list_capability_summaries(app.state.project_root)

    @app.get("/api/capabilities/{capability_id}")
    def api_capability_detail(capability_id: str) -> dict[str, Any]:
        return app.state.runtime.inspect_capability(app.state.project_root, capability_id)

    @app.get("/api/runs/{run_id}")
    def api_run_detail(run_id: str) -> dict[str, Any]:
        try:
            return app.state.runtime.get_run(app.state.project_root, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found") from exc

    @app.get("/report", response_class=PlainTextResponse)
    def report() -> str:
        try:
            report_path = app.state.runtime.materialize_report(app.state.project_root)
        except (WorkspaceError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return report_path.read_text(encoding="utf-8")

    @app.post("/episodes")
    def create_episode(goal: str = Form(...)) -> RedirectResponse:
        if not goal.strip():
            raise HTTPException(status_code=400, detail="Goal must not be empty")
        app.state.runtime.create_episode(app.state.project_root, goal)
        return RedirectResponse("/", status_code=303)

    @app.post("/episodes/switch")
    def switch_episode(episode_id: str = Form(...)) -> RedirectResponse:
        try:
            app.state.runtime.switch_episode(app.state.project_root, episode_id.strip())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse("/", status_code=303)

    @app.post("/workflow/start")
    def start_workflow() -> RedirectResponse:
        _apply_action(app.state.runtime.start_agent_workflow, app.state.project_root)
        return RedirectResponse("/", status_code=303)

    @app.post("/workflow/continue")
    def continue_workflow(
        state_version: int | None = Form(default=None),
        resume_token: str | None = Form(default=None),
    ) -> RedirectResponse:
        try:
            _apply_action(
                app.state.runtime.continue_agent_workflow,
                app.state.project_root,
                expected_state_version=state_version,
                resume_token=resume_token,
            )
        except StaleStateError:
            return RedirectResponse("/?stale=1", status_code=303)
        return RedirectResponse("/", status_code=303)

    @app.post("/workflow/execute")
    def execute_workflow_action() -> RedirectResponse:
        snapshot = _apply_action(app.state.runtime.execute_selected_action, app.state.project_root)
        location = "/"
        if snapshot.runs:
            location = f"/?run_id={snapshot.runs[-1]['run_id']}"
        return RedirectResponse(location, status_code=303)

    @app.post("/workflow/feedback")
    def submit_feedback(
        interrupt_id: str = Form(...),
        content: str = Form(...),
        kind: str = Form(default="clarification"),
        state_version: int | None = Form(default=None),
        resume_token: str | None = Form(default=None),
    ) -> RedirectResponse:
        if not content.strip():
            raise HTTPException(status_code=400, detail="Feedback content must not be empty")
        try:
            _apply_action(
                app.state.runtime.submit_feedback,
                app.state.project_root,
                interrupt_id=interrupt_id,
                content=content,
                kind=kind,
                actor="enzyme-web-host",
                expected_state_version=state_version,
                resume_token=resume_token,
            )
        except StaleStateError:
            return RedirectResponse("/?stale=1", status_code=303)
        return RedirectResponse("/", status_code=303)

    @app.post("/workflow/gates/{gate_id}/approve")
    def approve_gate(
        gate_id: str,
        state_version: int | None = Form(default=None),
        resume_token: str | None = Form(default=None),
    ) -> RedirectResponse:
        try:
            _apply_action(
                app.state.runtime.approve_gate,
                app.state.project_root,
                gate_id=gate_id,
                actor="enzyme-web-host",
                expected_state_version=state_version,
                resume_token=resume_token,
            )
        except StaleStateError:
            return RedirectResponse("/?stale=1", status_code=303)
        return RedirectResponse("/", status_code=303)

    @app.post("/workflow/gates/{gate_id}/reject")
    def reject_gate(
        gate_id: str,
        state_version: int | None = Form(default=None),
        resume_token: str | None = Form(default=None),
    ) -> RedirectResponse:
        try:
            _apply_action(
                app.state.runtime.reject_gate,
                app.state.project_root,
                gate_id=gate_id,
                actor="enzyme-web-host",
                expected_state_version=state_version,
                resume_token=resume_token,
            )
        except StaleStateError:
            return RedirectResponse("/?stale=1", status_code=303)
        return RedirectResponse("/", status_code=303)

    @app.post("/report")
    def build_report() -> RedirectResponse:
        try:
            app.state.runtime.materialize_report(app.state.project_root)
        except (WorkspaceError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse("/", status_code=303)

    return app


def _apply_action(action, project_root: Path, **kwargs):
    try:
        return action(project_root, **kwargs)
    except StaleStateError:
        raise
    except (WorkspaceError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _resolve_project_root(project_root: Path | None) -> Path:
    if project_root is not None:
        return project_root.resolve()
    configured = os.environ.get("ENZYME_PROJECT_ROOT")
    if configured:
        return Path(configured).resolve()
    return Path.cwd().resolve()


def _render_index(runtime: HostRuntime, project_root: Path, *, run_id: str | None, stale: bool) -> str:
    try:
        snapshot = runtime.get_status(project_root)
    except WorkspaceError as exc:
        try:
            context = runtime.load_project(project_root)
        except WorkspaceError:
            return _render_empty(project_root)
        if "No active episode" in str(exc):
            return _render_project_without_episode(context.root, context.config.project_name)
        return _render_empty(project_root)

    selected_run = None
    active_run_id = run_id
    if run_id:
        try:
            selected_run = runtime.get_run(project_root, run_id)
        except FileNotFoundError:
            selected_run = None
    elif snapshot.runs:
        active_run_id = str(snapshot.runs[-1]["run_id"])
        selected_run = runtime.get_run(project_root, active_run_id)

    report_text = ""
    report_path = Path(snapshot.project_root) / "episodes" / snapshot.episode_id / "report.md"
    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")

    agent = snapshot.agent_state if isinstance(snapshot.agent_state, dict) else {}
    session = agent.get("session") if isinstance(agent.get("session"), dict) else {}
    selected_action = agent.get("selected_action") if isinstance(agent.get("selected_action"), dict) else None
    progress = snapshot.progress_summary if isinstance(snapshot.progress_summary, dict) else {}
    backend = snapshot.agent_backend if isinstance(snapshot.agent_backend, dict) else {}
    sidecar_meta = backend.get("sidecar") if isinstance(backend.get("sidecar"), dict) else {}
    gate_interrupts = {
        str(item.get("gate_id")): item
        for item in snapshot.pending_interrupts
        if isinstance(item, dict) and item.get("gate_id")
    }

    current_status = escape(str(snapshot.stop_reason or agent.get("status", "idle")))
    operational_status = escape(str(agent.get("status", "idle")))
    needs_user_intervention = "Yes" if snapshot.needs_user_intervention else "No"
    current_focus = _display_text(progress.get("current_focus"), "No current focus available.")
    current_blocker = _display_text(
        progress.get("current_blocker") or progress.get("waiting_on"),
        "No blocker recorded.",
    )
    next_step = _display_text(snapshot.next_step_suggestion or progress.get("next_step"), "No next step suggestion recorded.")
    plain_language_explanation = _display_text(snapshot.plain_language_explanation, "No summary available.")
    technical_explanation = _display_text(snapshot.technical_explanation, "No technical explanation available.")
    resume_token = _display_text(session.get("resume_token"), "-")
    state_version = _display_text(session.get("active_state_version"), "-")
    recent_completed_items = [str(item) for item in progress.get("recent_completed") or [] if str(item).strip()]
    recent_completed_html = "".join(f"<li>{escape(item)}</li>" for item in recent_completed_items) or "<li>No recent completed milestones.</li>"

    backend_name = _display_text(backend.get("backend"), "heuristic")
    backend_state = "degraded" if backend.get("degraded") else ("blocked" if agent.get("status") == "blocked" else "healthy")
    fallback_state = "active" if backend.get("fallback_used") else "inactive"
    sidecar_error = _display_text(backend.get("last_error_summary"), "None")
    provider = _display_text(backend.get("provider"), "-")
    model = _display_text(backend.get("model"), "-")
    sidecar_name = _display_text(sidecar_meta.get("name"), "-")
    sidecar_version = _display_text(sidecar_meta.get("version"), "-")
    stale_banner = '<p class="notice">Workflow state was stale. The page has been refreshed to the latest canonical state.</p>' if stale else ""

    episode_options = "".join(
        _render_episode_option(episode_id, active_episode_id=snapshot.episode_id)
        for episode_id in snapshot.available_episode_ids
    )
    recent_runs_html = "".join(_render_run_item(item, active_run_id=active_run_id) for item in reversed(snapshot.runs[-6:]))
    capability_summaries_html = "".join(_render_capability_summary(item) for item in snapshot.capability_summaries)
    decision_trace = list(agent.get("decision_trace") or []) if isinstance(agent, dict) else []
    trace_html = "".join(_render_trace_item(item) for item in reversed(decision_trace[-8:]))
    workflow_audit_html = "".join(_render_workflow_event(item) for item in reversed(snapshot.workflow_audit[-10:]))
    report_preview = escape(report_text[:3000]) if report_text else "No report generated yet."
    run_detail = escape(json.dumps(selected_run, indent=2, ensure_ascii=False)) if selected_run else "No run selected."
    agent_preview = escape(json.dumps(agent, indent=2, ensure_ascii=False))
    evidence_preview = escape(json.dumps(snapshot.execution_evidence, indent=2, ensure_ascii=False))
    policy_preview = escape(
        json.dumps(
            {
                "trust_decision": (selected_action or {}).get("trust_decision"),
                "policy_reason": (selected_action or {}).get("policy_reason"),
                "policy_summary": (selected_action or {}).get("policy_summary"),
                "policy_rule_id": (selected_action or {}).get("policy_rule_id"),
                "policy_scope": (selected_action or {}).get("policy_scope"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    timeline_items = _build_timeline_items(
        snapshot=snapshot,
        selected_run=selected_run,
        active_run_id=active_run_id,
        session=session,
        selected_action=selected_action,
        gate_interrupts=gate_interrupts,
    )
    timeline_html = "".join(_render_timeline_item(item) for item in timeline_items)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenZyme Web Host</title>
  <style>{_STYLE}</style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div>
        <p class="eyebrow">OpenZyme Web Host</p>
        <h1>{escape(snapshot.project_name)}</h1>
        <p class="lede">No-bridge validation surface bound to <code>{escape(snapshot.project_root)}</code></p>
        <p class="hero-note">The primary view is reconstructed from canonical workflow state, not from a separate browser chat history.</p>
        {stale_banner}
      </div>
      <div class="hero-card">
        <div><span>Episode</span><strong>{escape(snapshot.episode_id)}</strong></div>
        <div><span>Workflow Status</span><strong>{current_status}</strong></div>
        <div><span>Operational Status</span><strong>{operational_status}</strong></div>
        <div><span>Needs User Action</span><strong>{needs_user_intervention}</strong></div>
        <div><span>Current Focus</span><strong>{escape(current_focus)}</strong></div>
        <div><span>Blocker</span><strong>{escape(current_blocker)}</strong></div>
        <div><span>Next Step</span><strong>{escape(next_step)}</strong></div>
        <div><span>Backend</span><strong>{escape(backend_name)}</strong></div>
        <div><span>Backend State</span><strong>{escape(backend_state)}</strong></div>
        <div><span>Fallback</span><strong>{escape(fallback_state)}</strong></div>
        <div><span>Resume Token</span><strong>{escape(resume_token)}</strong></div>
        <div><span>State Version</span><strong>{escape(state_version)}</strong></div>
      </div>
    </section>

    <section class="experience">
      <article class="panel panel-wide panel-strong">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Primary Narrative</p>
            <h2>Main Timeline</h2>
          </div>
          <p class="panel-caption">Conversation-style timeline rendered from canonical snapshot fields such as explanation, progress summary, selected action, interrupts, gates, runs, and workflow audit.</p>
        </div>
        <p class="summary-lede">{escape(plain_language_explanation)}</p>
        <ol class="timeline-list">{timeline_html}</ol>
      </article>

      <aside class="sidebar">
        <article class="panel">
          <h2>Workflow Controls</h2>
          <p class="muted">Primary approvals and execution affordances now live beside the relevant timeline cards. Project-level controls stay here.</p>
          <form method="post" action="/episodes" class="stack">
            <label>New episode goal</label>
            <textarea name="goal" rows="4" placeholder="Design a more selective inhibitor"></textarea>
            <button type="submit">Create Episode</button>
          </form>
          <form method="post" action="/episodes/switch" class="stack">
            <label>Switch active episode</label>
            <select name="episode_id">{episode_options}</select>
            <button type="submit">Switch Episode</button>
          </form>
          <form method="post" action="/workflow/start" class="inline-form">
            <button type="submit">Start Workflow</button>
          </form>
          <form method="post" action="/report" class="inline-form">
            <button type="submit">Generate Report</button>
            <a class="secondary" href="/report">Open Report</a>
          </form>
        </article>

        <article class="panel">
          <h2>Project Context</h2>
          <div class="context-grid">
            <div class="summary-card">
              <span>Goal</span>
              <p>{escape(snapshot.goal.strip() or "No episode goal recorded.")}</p>
            </div>
            <div class="summary-card">
              <span>Recent Completed</span>
              <ul class="summary-list">{recent_completed_html}</ul>
            </div>
          </div>
          <p><strong>Recent Runs</strong></p>
          <div class="run-list">{recent_runs_html or "<p>No runs yet.</p>"}</div>
        </article>
      </aside>
    </section>

    <section class="auxiliary">
      <div class="panel-header auxiliary-header">
        <div>
          <p class="eyebrow">Secondary Inspection</p>
          <h2>Trace / Debug / Raw State / Report</h2>
        </div>
        <p class="panel-caption">These panels remain available for provenance, troubleshooting, and auditability, but they no longer occupy the main interaction lane.</p>
      </div>
      <div class="secondary-grid">
        <article class="panel">
          <h2>Backend Provenance</h2>
          <p><strong>Current backend</strong>: {escape(backend_name)}</p>
          <p><strong>State</strong>: {escape(backend_state)}</p>
          <p><strong>Provider / model</strong>: {escape(provider)} / {escape(model)}</p>
          <p><strong>Sidecar</strong>: {escape(sidecar_name)} {escape(sidecar_version)}</p>
          <p><strong>Last sidecar error</strong>: {escape(sidecar_error)}</p>
          <p><strong>Capability inspect summaries</strong></p>
          <div class="run-list">{capability_summaries_html or "<p>No capability summaries available.</p>"}</div>
        </article>

        <article class="panel">
          <h2>Run Detail</h2>
          <p class="muted">Recent run cards stay in the main timeline. Full manifests stay here.</p>
          <pre id="run-detail">{run_detail}</pre>
        </article>

        <article class="panel">
          <h2>Technical Explanation</h2>
          <pre>{escape(technical_explanation)}</pre>
          <p><strong>Selected Action Policy</strong></p>
          <pre>{policy_preview}</pre>
        </article>

        <article class="panel">
          <h2>Workflow Trace</h2>
          <p><strong>Decision Trace</strong></p>
          <div class="run-list">{trace_html or "<p>No decisions recorded yet.</p>"}</div>
          <p><strong>Workflow Audit</strong></p>
          <div class="run-list">{workflow_audit_html or "<p>No workflow audit events yet.</p>"}</div>
        </article>

        <article class="panel">
          <h2>Execution Evidence</h2>
          <pre>{evidence_preview}</pre>
        </article>

        <article class="panel panel-wide">
          <h2>Agent State</h2>
          <pre>{agent_preview}</pre>
        </article>

        <article class="panel panel-wide">
          <h2>Report Preview</h2>
          <pre>{report_preview}</pre>
        </article>
      </div>
    </section>
  </main>
</body>
</html>"""


def _build_timeline_items(
    *,
    snapshot: Any,
    selected_run: dict[str, Any] | None,
    active_run_id: str | None,
    session: dict[str, Any],
    selected_action: dict[str, Any] | None,
    gate_interrupts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    progress = snapshot.progress_summary if isinstance(snapshot.progress_summary, dict) else {}
    items: list[dict[str, Any]] = []
    approved_gates = {
        str(item.get("gate_id")): item
        for item in snapshot.approval_gates
        if isinstance(item, dict) and str(item.get("status")) == "approved"
    }

    summary_actions: list[dict[str, Any]] = []
    if _should_offer_continue_workflow(snapshot=snapshot, selected_action=selected_action):
        summary_actions.append(
            _submit_action(
                "/workflow/continue",
                "Continue Workflow",
                hidden_fields=_resume_hidden_fields(session),
            )
        )
    items.append(
        {
            "id": "summary-current",
            "kind": "summary",
            "tone": "summary",
            "eyebrow": "System update",
            "title": _display_text(snapshot.stop_reason, "active").replace("_", " ").title(),
            "body": [
                _display_text(snapshot.plain_language_explanation, "No narrative summary available."),
                f"Current blocker: {_display_text(progress.get('current_blocker') or progress.get('waiting_on'), 'No blocker recorded.')}",
                f"Next step: {_display_text(snapshot.next_step_suggestion or progress.get('next_step'), 'No next step suggestion recorded.')}",
            ],
            "details": [
                ("Current focus", _display_text(progress.get("current_focus"), "No current focus available.")),
                ("Needs user action", "Yes" if snapshot.needs_user_intervention else "No"),
                ("Recent completed", ", ".join(str(item) for item in progress.get("recent_completed") or []) or "None yet"),
            ],
            "refs": {
                "episode_id": snapshot.episode_id,
                "state_version": _display_text(session.get("active_state_version"), "-"),
            },
            "actions": summary_actions,
        }
    )

    if selected_action:
        gate_id = _optional_text(selected_action.get("gate_id"))
        action_actions: list[dict[str, Any]] = []
        if selected_action.get("tool_action") and gate_id is None:
            action_actions.append(_submit_action("/workflow/execute", "Execute Selected Action"))
        items.append(
            {
                "id": f"action-{_display_text(selected_action.get('action_id'), 'current')}",
                "kind": "selected_action",
                "tone": "action",
                "eyebrow": "Selected action",
                "title": _display_text(selected_action.get("title"), "No action selected"),
                "body": [
                    _display_text(selected_action.get("plain_language_explanation") or selected_action.get("rationale"), "No plain-language action summary recorded."),
                ],
                "details": [
                    ("Action type", _display_text(selected_action.get("kind"), "-")),
                    ("Capability", _display_text(selected_action.get("capability_id"), "-")),
                    ("Tool", _display_text((selected_action.get("tool_action") or {}).get("tool"), "Not executable")),
                    ("Risk", _display_text((selected_action.get("tool_action") or {}).get("risk_level"), _display_text(selected_action.get("trust_decision"), "-"))),
                ],
                "refs": _compact_refs(
                    action_id=selected_action.get("action_id"),
                    action_revision=selected_action.get("action_revision"),
                    gate_id=selected_action.get("gate_id"),
                    capability_id=selected_action.get("capability_id"),
                ),
                "actions": action_actions,
            }
        )

    for gate in snapshot.approval_gates:
        if not isinstance(gate, dict):
            continue
        gate_id = str(gate.get("gate_id") or "")
        interrupt = gate_interrupts.get(gate_id)
        actions: list[dict[str, Any]] = []
        if gate.get("status") == "pending":
            actions.extend(
                [
                    _submit_action(
                        f"/workflow/gates/{gate_id}/approve",
                        "Approve and Continue",
                        hidden_fields=_resume_hidden_fields(interrupt or {}),
                    ),
                    _submit_action(
                        f"/workflow/gates/{gate_id}/reject",
                        "Reject and Stop",
                        tone="secondary",
                        hidden_fields=_resume_hidden_fields(interrupt or {}),
                    ),
                ]
            )
        elif gate_id and selected_action and gate_id == selected_action.get("gate_id") and selected_action.get("tool_action"):
            actions.append(_submit_action("/workflow/execute", "Execute Approved Action"))
        items.append(
            {
                "id": f"gate-{gate_id or 'unknown'}",
                "kind": "approval_gate",
                "tone": "gate",
                "eyebrow": "Approval gate",
                "title": _display_text(gate.get("plain_language_reason"), "Review this gate before continuing."),
                "body": [
                    _display_text(gate.get("policy_reason"), "No policy reason recorded."),
                    _display_text((interrupt or {}).get("plain_language_explanation"), "The workflow paused here waiting for an approval decision."),
                ],
                "details": [
                    ("Status", _display_text(gate.get("status"), "pending")),
                    ("Risk level", _display_text(gate.get("risk_level"), "normal")),
                    ("Required feedback", _display_text(gate.get("required_feedback_type"), "-")),
                ],
                "refs": _compact_refs(
                    gate_id=gate.get("gate_id"),
                    action_id=gate.get("action_id"),
                    interrupt_id=(interrupt or {}).get("interrupt_id"),
                    policy_rule_id=gate.get("policy_rule_id"),
                ),
                "actions": actions,
            }
        )

    for interrupt in snapshot.pending_interrupts:
        if not isinstance(interrupt, dict) or interrupt.get("kind") == "approval_request":
            continue
        items.append(
            {
                "id": f"interrupt-{_display_text(interrupt.get('interrupt_id'), 'unknown')}",
                "kind": "interrupt",
                "tone": "interrupt",
                "eyebrow": "Pending interrupt",
                "title": _display_text(interrupt.get("title"), "Feedback requested"),
                "body": [
                    _display_text(interrupt.get("plain_language_explanation") or interrupt.get("prompt"), "The workflow needs user feedback."),
                    f"Suggested response: {_display_text(interrupt.get('suggested_user_action'), 'Provide clarification or a decision.')}",
                ],
                "details": [
                    ("Interrupt kind", _display_text(interrupt.get("kind"), "clarification_request")),
                    ("Status", _display_text(interrupt.get("status"), "pending")),
                    ("Created at", _display_text(interrupt.get("created_at"), "-")),
                ],
                "refs": _compact_refs(
                    interrupt_id=interrupt.get("interrupt_id"),
                    action_id=interrupt.get("related_action_id"),
                    gate_id=interrupt.get("gate_id"),
                    state_version=interrupt.get("active_state_version"),
                ),
                "actions": [
                    _feedback_action(interrupt),
                ],
            }
        )

    for item in reversed(snapshot.runs[-3:]):
        if not isinstance(item, dict):
            continue
        run_id = str(item.get("run_id") or "")
        run_detail = selected_run if selected_run and run_id == active_run_id else None
        items.append(
            {
                "id": f"run-{run_id or 'unknown'}",
                "kind": "run_result",
                "tone": "run",
                "eyebrow": "Recent run result",
                "title": _display_text(_run_title(item, run_detail), "Recent run"),
                "body": [
                    _display_text(_run_summary(item, run_detail), "No run summary available."),
                ],
                "details": _run_details(item, run_detail),
                "refs": _compact_refs(
                    run_id=item.get("run_id"),
                    step_id=item.get("step_id"),
                    manifest_path=item.get("manifest_path"),
                ),
                "actions": [
                    {
                        "type": "link",
                        "href": f"/?run_id={escape(run_id)}#run-detail",
                        "label": "Open Run Detail",
                        "tone": "secondary",
                    }
                ],
            }
        )

    for event in _select_audit_highlights(snapshot.workflow_audit):
        items.append(
            {
                "id": f"audit-{_display_text(event.get('timestamp'), _display_text(event.get('event_type'), 'event'))}",
                "kind": "workflow_event",
                "tone": "audit",
                "eyebrow": "Workflow audit highlight",
                "title": _workflow_event_title(event),
                "body": [_workflow_event_summary(event)],
                "details": [
                    ("Timestamp", _display_text(event.get("timestamp"), "-")),
                ],
                "refs": _compact_refs(**(event.get("refs") if isinstance(event.get("refs"), dict) else {})),
                "actions": [],
            }
        )

    return items


def _should_offer_continue_workflow(*, snapshot: Any, selected_action: dict[str, Any] | None) -> bool:
    if snapshot.stop_reason != "active" or snapshot.pending_interrupts:
        return False
    if not selected_action:
        return True
    return not bool(selected_action.get("tool_action"))


def _select_audit_highlights(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    interesting = {
        "action_selected",
        "action_execution_started",
        "action_execution_finished",
        "observation_recorded",
        "feedback_recorded",
        "gate_transitioned",
        "capability_inspected",
    }
    selected = [item for item in events if isinstance(item, dict) and item.get("event_type") in interesting]
    return selected[-4:]


def _workflow_event_title(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "workflow_event")
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    refs = event.get("refs") if isinstance(event.get("refs"), dict) else {}
    tool = _optional_text(refs.get("tool")) or _optional_text(details.get("tool"))
    status = _optional_text(details.get("status"))
    if event_type == "action_selected":
        return "Workflow selected the next action"
    if event_type == "action_execution_started":
        return f"Execution started for {tool or 'the selected tool'}"
    if event_type == "action_execution_finished":
        return f"Execution finished with status {status or 'unknown'}"
    if event_type == "observation_recorded":
        return "Observation recorded after execution"
    if event_type == "feedback_recorded":
        return "User feedback was recorded"
    if event_type == "gate_transitioned":
        return "Approval gate changed state"
    if event_type == "capability_inspected":
        return "Capability detail was inspected"
    return event_type.replace("_", " ").title()


def _workflow_event_summary(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "workflow_event")
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    refs = event.get("refs") if isinstance(event.get("refs"), dict) else {}
    if event_type == "action_selected":
        action_id = _display_text(refs.get("action_id"), "an action")
        return f"The runtime recorded a canonical action selection for {action_id}."
    if event_type == "action_execution_started":
        return f"The selected action started through tool {_display_text(refs.get('tool'), 'unknown')}."
    if event_type == "action_execution_finished":
        return f"Run {_display_text(refs.get('run_id'), 'unknown')} completed with status {_display_text(details.get('status'), 'unknown')}."
    if event_type == "observation_recorded":
        return f"Observation {_display_text(refs.get('observation_id'), 'unknown')} captured the result of the latest step."
    if event_type == "feedback_recorded":
        return f"Feedback of type {_display_text(details.get('kind'), 'comment')} updated the canonical workflow state."
    if event_type == "gate_transitioned":
        return f"Gate {_display_text(refs.get('gate_id'), 'unknown')} received {_display_text(details.get('kind'), 'feedback')}."
    if event_type == "capability_inspected":
        return f"Capability {_display_text(refs.get('capability_id'), 'unknown')} was inspected for execution context."
    return _display_text(details or refs, "No additional details.")


def _run_title(item: dict[str, Any], run_detail: dict[str, Any] | None) -> str:
    tool = _optional_text(item.get("tool"))
    if run_detail:
        tool = _optional_text(run_detail.get("tool")) or _optional_text(
            ((run_detail.get("adapter_metadata") if isinstance(run_detail.get("adapter_metadata"), dict) else {}).get("tool_contract") or {}).get("adapter_id")
        ) or tool
    step_id = _display_text(item.get("step_id"), "run")
    if tool:
        return f"{tool} for {step_id}"
    return f"Run result for {step_id}"


def _run_summary(item: dict[str, Any], run_detail: dict[str, Any] | None) -> str:
    if run_detail:
        result = run_detail.get("result") if isinstance(run_detail.get("result"), dict) else {}
        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        if output.get("output_path"):
            return f"Produced artifact at {output['output_path']}."
        if output.get("output_dir"):
            return f"Produced artifacts under {output['output_dir']}."
        if result.get("error"):
            return f"Execution reported error: {result['error']}."
    return f"Status {_display_text(item.get('status'), 'unknown')} for step {_display_text(item.get('step_id'), 'unknown')}."


def _run_details(item: dict[str, Any], run_detail: dict[str, Any] | None) -> list[tuple[str, str]]:
    details = [
        ("Status", _display_text(item.get("status"), "unknown")),
        ("Step", _display_text(item.get("step_id"), "-")),
    ]
    if run_detail:
        result = run_detail.get("result") if isinstance(run_detail.get("result"), dict) else {}
        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        primary_artifact = _optional_text(output.get("output_path")) or _optional_text(output.get("output_dir"))
        if primary_artifact:
            details.append(("Primary artifact", primary_artifact))
        error = _optional_text(result.get("error"))
        if error:
            details.append(("Error", error))
    return details[:4]


def _render_timeline_item(item: dict[str, Any]) -> str:
    body_html = "".join(f"<p>{escape(str(text))}</p>" for text in item.get("body") or [])
    details_html = "".join(
        f"<div class=\"meta-pair\"><span>{escape(str(label))}</span><strong>{escape(str(value))}</strong></div>"
        for label, value in item.get("details") or []
    )
    refs_html = "".join(
        f"<li><span>{escape(str(key))}</span><code>{escape(str(value))}</code></li>"
        for key, value in (item.get("refs") or {}).items()
    )
    actions_html = "".join(_render_timeline_action(action) for action in item.get("actions") or [])
    workbench_context = item.get("workbench_context")
    workbench_attr = ""
    if isinstance(workbench_context, dict):
        workbench_attr = f" data-workbench-context=\"{escape(json.dumps(workbench_context, ensure_ascii=False))}\""
    return f"""
<li class="timeline-entry" data-kind="{escape(str(item.get('kind', 'event')))}" data-item-id="{escape(str(item.get('id', 'item')))}"{workbench_attr}>
  <article class="timeline-card tone-{escape(str(item.get('tone', 'default')))}">
    <p class="timeline-eyebrow">{escape(str(item.get('eyebrow', 'Timeline item')))}</p>
    <h3>{escape(str(item.get('title', 'Untitled item')))}</h3>
    <div class="timeline-body">{body_html}</div>
    <div class="timeline-meta">{details_html}</div>
    <ul class="ref-list">{refs_html}</ul>
    <div class="timeline-actions">{actions_html}</div>
  </article>
</li>"""


def _render_timeline_action(action: dict[str, Any]) -> str:
    action_type = str(action.get("type") or "button")
    tone = escape(str(action.get("tone") or "primary"))
    if action_type == "link":
        return f'<a class="action-link tone-{tone}" href="{escape(str(action.get("href") or "#"))}">{escape(str(action.get("label") or "Open"))}</a>'
    if action_type == "button":
        disabled = " disabled" if action.get("disabled") else ""
        return f'<button type="button" class="action-button tone-{tone}"{disabled}>{escape(str(action.get("label") or "Unavailable"))}</button>'
    if action_type == "feedback":
        hidden_fields = "".join(
            f'<input type="hidden" name="{escape(name)}" value="{escape(str(value))}">'
            for name, value in (action.get("hidden_fields") or {}).items()
            if value is not None and str(value) != ""
        )
        return f"""
<form method="post" action="{escape(str(action.get('action') or '/workflow/feedback'))}" class="stack timeline-form">
  {hidden_fields}
  <label>{escape(str(action.get("label") or "Submit feedback"))}</label>
  <textarea name="content" rows="3" placeholder="{escape(str(action.get('placeholder') or 'Provide the requested feedback'))}"></textarea>
  <button type="submit" class="tone-{tone}">{escape(str(action.get('submit_label') or 'Submit Feedback'))}</button>
</form>"""
    hidden_fields = "".join(
        f'<input type="hidden" name="{escape(name)}" value="{escape(str(value))}">'
        for name, value in (action.get("hidden_fields") or {}).items()
        if value is not None and str(value) != ""
    )
    return f"""
<form method="post" action="{escape(str(action.get('action') or '#'))}" class="inline-form timeline-inline-action">
  {hidden_fields}
  <button type="submit" class="tone-{tone}">{escape(str(action.get("label") or "Submit"))}</button>
</form>"""


def _submit_action(
    action: str,
    label: str,
    *,
    tone: str = "primary",
    hidden_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "submit",
        "action": action,
        "label": label,
        "tone": tone,
        "hidden_fields": hidden_fields or {},
    }


def _feedback_action(interrupt: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "feedback",
        "action": "/workflow/feedback",
        "label": _display_text(interrupt.get("title"), "Submit feedback"),
        "submit_label": "Submit Feedback",
        "placeholder": _display_text(interrupt.get("suggested_user_action"), "Provide the requested feedback"),
        "hidden_fields": {
            "interrupt_id": interrupt.get("interrupt_id"),
            "kind": "clarification",
            "state_version": interrupt.get("active_state_version"),
            "resume_token": interrupt.get("resume_token"),
        },
    }


def _resume_hidden_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "state_version": payload.get("active_state_version"),
        "resume_token": payload.get("resume_token"),
    }


def _compact_refs(**refs: Any) -> dict[str, str]:
    compact: dict[str, str] = {}
    for key, value in refs.items():
        rendered = _optional_text(value)
        if rendered:
            compact[key] = rendered
    return compact


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _display_text(value: Any, fallback: str) -> str:
    rendered = _optional_text(value)
    return rendered or fallback


def _render_capability_summary(summary: dict[str, Any]) -> str:
    capability_id = escape(str(summary.get("capability_id", "-")))
    title = escape(str(summary.get("title", capability_id)))
    detail = escape(str(summary.get("summary", "")))
    server_name = escape(str(summary.get("server_name", "-")))
    return f"""
<div class="run-item">
  <strong>{title}</strong>
  <span>{capability_id} via {server_name}</span>
  <p>{detail}</p>
</div>
"""


def _render_workflow_event(event: dict[str, Any]) -> str:
    title = escape(_workflow_event_title(event))
    summary = escape(_workflow_event_summary(event))
    timestamp = escape(str(event.get("timestamp", "-")))
    refs = event.get("refs")
    refs_text = escape(json.dumps(refs, ensure_ascii=False)) if isinstance(refs, dict) and refs else ""
    return f"""
<div class="run-item">
  <strong>{title}</strong>
  <span>{timestamp}</span>
  <p>{summary}</p>
  <code>{refs_text or "No refs recorded."}</code>
</div>
"""


def _render_empty(project_root: Path) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>{_STYLE}</style></head>
<body><main class="shell"><section class="hero"><div><p class="eyebrow">OpenZyme Web Host</p><h1>No project loaded</h1><p class="lede">Expected an initialized OpenZyme project at <code>{escape(str(project_root))}</code>.</p></div></section></main></body></html>"""


def _render_project_without_episode(project_root: Path, project_name: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>{_STYLE}</style></head>
<body>
<main class="shell">
  <section class="hero">
    <div>
      <p class="eyebrow">OpenZyme Web Host</p>
      <h1>{escape(project_name)}</h1>
      <p class="lede">Project loaded from <code>{escape(str(project_root))}</code>. Create the first episode to begin the workflow.</p>
    </div>
  </section>
  <section class="experience">
    <article class="panel panel-strong panel-wide">
      <h2>Main Timeline</h2>
      <p class="summary-lede">No canonical episode snapshot is active yet. Create the first episode to start a workflow-driven conversation surface.</p>
      <form method="post" action="/episodes" class="stack">
        <label>New episode goal</label>
        <textarea name="goal" rows="4" placeholder="Design a more selective inhibitor"></textarea>
        <button type="submit">Create Episode</button>
      </form>
    </article>
  </section>
</main>
</body>
</html>"""


def _render_run_item(item: dict[str, Any], *, active_run_id: str | None) -> str:
    run_id = str(item.get("run_id", "-"))
    selected = " active" if run_id == active_run_id else ""
    return (
        f'<a class="run-item{selected}" href="/?run_id={escape(run_id)}#run-detail">'
        f"<strong>{escape(str(item.get('step_id', '-')))}</strong>"
        f"<span>{escape(str(item.get('status', 'unknown')))}</span>"
        f"<code>{escape(run_id)}</code>"
        "</a>"
    )


def _render_trace_item(item: dict[str, Any]) -> str:
    return (
        '<div class="run-item">'
        f"<strong>{escape(str(item.get('kind', 'trace')))}</strong>"
        f"<span>{escape(str(item.get('summary', '-')))}</span>"
        f"<code>{escape(str(item.get('created_at', '-')))}</code>"
        "</div>"
    )


def _render_episode_option(episode_id: str, *, active_episode_id: str) -> str:
    selected = " selected" if episode_id == active_episode_id else ""
    return f'<option value="{escape(episode_id)}"{selected}>{escape(episode_id)}</option>'


_STYLE = """
:root {
  --bg: #f3efe7;
  --paper: #fffdf8;
  --ink: #1f1d1a;
  --muted: #6d655b;
  --line: #d8cfc2;
  --accent: #1e6b52;
  --accent-2: #d58936;
  --accent-soft: rgba(30, 107, 82, 0.08);
  --warn-soft: rgba(213, 137, 54, 0.12);
  --rose-soft: rgba(166, 67, 52, 0.1);
  --shadow: 0 14px 40px rgba(56, 42, 19, 0.08);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Iowan Old Style", "Palatino Linotype", serif;
  color: var(--ink);
  background:
    radial-gradient(circle at top right, rgba(213, 137, 54, 0.18), transparent 30%),
    linear-gradient(135deg, #f6f2ea 0%, #efe7db 100%);
}
.shell { max-width: 1480px; margin: 0 auto; padding: 32px 20px 56px; }
.hero { display: grid; grid-template-columns: 1.45fr 1fr; gap: 18px; align-items: stretch; margin-bottom: 22px; }
.eyebrow { text-transform: uppercase; letter-spacing: 0.16em; font-size: 0.74rem; color: var(--accent); }
h1, h2, h3 { margin: 0 0 12px; font-weight: 700; }
h1 { font-size: clamp(2rem, 5vw, 4.5rem); line-height: 0.94; }
h2 { font-size: 1.2rem; }
h3 { font-size: 1.08rem; }
.lede, .muted, .panel-caption, .hero-note { color: var(--muted); }
.hero-note { max-width: 64ch; margin-top: 14px; }
.hero-card, .panel { background: color-mix(in srgb, var(--paper) 88%, white); border: 1px solid var(--line); border-radius: 20px; box-shadow: var(--shadow); }
.hero-card { display: grid; gap: 16px; padding: 22px; }
.hero-card span { display: block; color: var(--muted); font-size: 0.82rem; margin-bottom: 4px; }
.hero-card strong { font-size: 1.06rem; }
.experience { display: grid; grid-template-columns: minmax(0, 1.75fr) minmax(320px, 0.95fr); gap: 18px; align-items: start; }
.sidebar { display: grid; gap: 18px; }
.panel { padding: 20px; }
.panel-wide { min-width: 0; }
.panel-strong { background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(255, 252, 246, 0.92)); }
.panel-header { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; margin-bottom: 14px; }
.panel-caption { max-width: 48ch; margin: 0; }
.summary-lede { font-size: 1.12rem; line-height: 1.58; margin-top: 0; margin-bottom: 18px; }
.timeline-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 16px; }
.timeline-entry { position: relative; }
.timeline-entry::before {
  content: "";
  position: absolute;
  left: 19px;
  top: -12px;
  bottom: -12px;
  width: 2px;
  background: linear-gradient(180deg, rgba(30, 107, 82, 0.14), rgba(213, 137, 54, 0.22));
}
.timeline-entry:first-child::before { top: 26px; }
.timeline-entry:last-child::before { bottom: 26px; }
.timeline-card {
  position: relative;
  margin-left: 36px;
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 18px;
  background: rgba(255, 255, 255, 0.78);
}
.timeline-card::before {
  content: "";
  position: absolute;
  left: -26px;
  top: 22px;
  width: 12px;
  height: 12px;
  border-radius: 999px;
  background: var(--accent);
  box-shadow: 0 0 0 4px rgba(30, 107, 82, 0.12);
}
.timeline-card.tone-summary { background: linear-gradient(135deg, rgba(30, 107, 82, 0.08), rgba(255, 255, 255, 0.92)); }
.timeline-card.tone-gate::before { background: var(--accent-2); box-shadow: 0 0 0 4px rgba(213, 137, 54, 0.15); }
.timeline-card.tone-interrupt::before { background: #a64334; box-shadow: 0 0 0 4px rgba(166, 67, 52, 0.12); }
.timeline-card.tone-run::before { background: #427899; box-shadow: 0 0 0 4px rgba(66, 120, 153, 0.12); }
.timeline-card.tone-audit::before { background: #7d6b3d; box-shadow: 0 0 0 4px rgba(125, 107, 61, 0.12); }
.timeline-card.tone-workbench::before { background: #5f4a7a; box-shadow: 0 0 0 4px rgba(95, 74, 122, 0.12); }
.timeline-eyebrow { margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.12em; font-size: 0.74rem; color: var(--muted); }
.timeline-body { display: grid; gap: 10px; margin-bottom: 12px; }
.timeline-body p { margin: 0; line-height: 1.55; }
.timeline-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 12px; }
.meta-pair { border: 1px solid var(--line); border-radius: 14px; padding: 12px; background: rgba(255, 255, 255, 0.6); display: grid; gap: 6px; }
.meta-pair span { color: var(--muted); font-size: 0.8rem; }
.meta-pair strong, .summary-card p { margin: 0; }
.ref-list { list-style: none; display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 14px; padding: 0; }
.ref-list li { display: inline-flex; gap: 8px; align-items: center; border: 1px solid var(--line); border-radius: 999px; padding: 6px 10px; background: rgba(255,255,255,0.7); font-size: 0.82rem; }
.ref-list span { color: var(--muted); }
.timeline-actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-start; }
.context-grid { display: grid; gap: 12px; margin-bottom: 14px; }
.summary-card { border: 1px solid var(--line); border-radius: 18px; padding: 16px; background: rgba(255,255,255,0.72); display: grid; gap: 8px; }
.summary-card span { color: var(--muted); font-size: 0.82rem; }
.summary-card ul { margin: 0; }
.summary-list { margin: 0; padding-left: 20px; display: grid; gap: 8px; }
.auxiliary { margin-top: 28px; }
.auxiliary-header { margin-bottom: 16px; }
.secondary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.stack { display: grid; gap: 10px; margin-bottom: 14px; }
.inline-form { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.timeline-inline-action { margin-bottom: 0; }
.timeline-form { min-width: min(100%, 340px); margin-bottom: 0; }
textarea, input, select, button, .secondary, .action-link {
  font: inherit;
  border-radius: 14px;
}
textarea, input, select {
  width: 100%;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.9);
  padding: 12px 14px;
}
button, .secondary, .action-link {
  border: none;
  background: var(--accent);
  color: white;
  padding: 11px 16px;
  text-decoration: none;
  cursor: pointer;
}
.secondary, .action-link.tone-secondary, .timeline-inline-action .tone-secondary { background: var(--accent-2); }
.action-button.tone-ghost { background: #8e8579; }
.timeline-inline-action .tone-primary, .timeline-form .tone-primary { background: var(--accent); }
.timeline-inline-action .tone-secondary, .timeline-form .tone-secondary { background: var(--accent-2); }
button[disabled] { opacity: 0.7; cursor: not-allowed; }
pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: "SFMono-Regular", "Cascadia Code", monospace;
  font-size: 0.9rem;
  background: rgba(216, 207, 194, 0.24);
  padding: 14px;
  border-radius: 16px;
}
.run-list { display: grid; gap: 10px; }
.run-item {
  display: grid;
  gap: 4px;
  color: inherit;
  text-decoration: none;
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 12px 14px;
  background: rgba(255,255,255,0.72);
}
.run-item.active { border-color: var(--accent); background: var(--accent-soft); }
.notice {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding: 10px 14px;
  border-radius: 999px;
  border: 1px solid rgba(166, 67, 52, 0.2);
  background: var(--rose-soft);
}
code {
  font-family: "SFMono-Regular", "Cascadia Code", monospace;
  font-size: 0.88rem;
}
@media (max-width: 1160px) {
  .hero, .experience, .secondary-grid, .panel-header { grid-template-columns: 1fr; }
  .panel-header { flex-direction: column; }
}
@media (max-width: 820px) {
  .shell { padding-inline: 14px; }
  .timeline-card { margin-left: 28px; }
  .timeline-entry::before { left: 14px; }
  .timeline-card::before { left: -21px; }
  .timeline-meta { grid-template-columns: 1fr; }
}
"""
