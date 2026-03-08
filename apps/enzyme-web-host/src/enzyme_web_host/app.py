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
    if run_id:
        try:
            selected_run = runtime.get_run(project_root, run_id)
        except FileNotFoundError:
            selected_run = None
    elif snapshot.runs:
        selected_run = runtime.get_run(project_root, snapshot.runs[-1]["run_id"])

    report_text = ""
    report_path = Path(snapshot.project_root) / "episodes" / snapshot.episode_id / "report.md"
    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")

    agent = snapshot.agent_state
    session = agent.get("session") if isinstance(agent, dict) else {}
    session = session if isinstance(session, dict) else {}
    selected_action = agent.get("selected_action") if isinstance(agent, dict) else None
    selected_action = selected_action if isinstance(selected_action, dict) else None
    gate_interrupts = {
        str(item.get("gate_id")): item
        for item in snapshot.pending_interrupts
        if isinstance(item, dict) and item.get("gate_id")
    }
    episode_options = "".join(
        _render_episode_option(episode_id, active_episode_id=snapshot.episode_id)
        for episode_id in snapshot.available_episode_ids
    )
    runs_html = "".join(_render_run_item(item, active_run_id=run_id) for item in snapshot.runs[-8:])
    interrupts_html = "".join(_render_interrupt_item(item) for item in snapshot.pending_interrupts)
    gates_html = "".join(_render_gate_item(item) for item in snapshot.approval_gates)
    decision_trace = list(agent.get("decision_trace") or []) if isinstance(agent, dict) else []
    trace_html = "".join(_render_trace_item(item) for item in reversed(decision_trace[-8:]))
    report_preview = escape(report_text[:3000]) if report_text else "No report generated yet."
    run_detail = escape(json.dumps(selected_run, indent=2)) if selected_run else "No run selected."
    agent_preview = escape(json.dumps(agent, indent=2))
    evidence_preview = escape(json.dumps(snapshot.execution_evidence, indent=2))
    next_action = escape(selected_action.get("title", "No action selected")) if selected_action else "No action selected"
    current_status = escape(str(agent.get("status", "idle")))
    resume_token = escape(str(session.get("resume_token", "-")))
    state_version = escape(str(session.get("active_state_version", "-")))
    stale_banner = '<p class="notice">Workflow state was stale. The page has been refreshed to the latest canonical state.</p>' if stale else ""

    feedback_forms = "".join(_render_feedback_form(item) for item in snapshot.pending_interrupts if item.get("kind") != "approval_request")
    gate_forms = "".join(
        _render_gate_form(item, gate_interrupts.get(str(item.get("gate_id"))))
        for item in snapshot.approval_gates
        if item.get("status") == "pending"
    )

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
        <p class="lede">Agent-aware host bound to <code>{escape(snapshot.project_root)}</code></p>
        {stale_banner}
      </div>
      <div class="hero-card">
        <div><span>Episode</span><strong>{escape(snapshot.episode_id)}</strong></div>
        <div><span>Agent Status</span><strong>{current_status}</strong></div>
        <div><span>Next Action</span><strong>{next_action}</strong></div>
        <div><span>Resume Token</span><strong>{resume_token}</strong></div>
        <div><span>State Version</span><strong>{state_version}</strong></div>
        <div><span>Pending Interrupts</span><strong>{escape(str(len(snapshot.pending_interrupts)))}</strong></div>
      </div>
    </section>
    <section class="grid">
      <article class="panel">
        <h2>Project Context</h2>
        <p><strong>Goal</strong></p>
        <pre>{escape(snapshot.goal.strip())}</pre>
        <p><strong>Recent Runs</strong></p>
        <div class="run-list">{runs_html or '<p>No runs yet.</p>'}</div>
        <p><strong>Decision Trace</strong></p>
        <div class="run-list">{trace_html or '<p>No decisions recorded yet.</p>'}</div>
      </article>
      <article class="panel">
        <h2>Workflow Actions</h2>
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
        <form method="post" action="/workflow/continue" class="inline-form">
          <input type="hidden" name="state_version" value="{escape(str(session.get('active_state_version', '')))}">
          <input type="hidden" name="resume_token" value="{escape(str(session.get('resume_token', '')))}">
          <button type="submit">Continue Workflow</button>
        </form>
        <form method="post" action="/workflow/execute" class="inline-form">
          <button type="submit">Execute Selected Action</button>
        </form>
        {gate_forms}
        {feedback_forms}
        <form method="post" action="/report" class="inline-form">
          <button type="submit">Generate Report</button>
          <a class="secondary" href="/report">Open Report</a>
        </form>
      </article>
      <article class="panel">
        <h2>Pending Interrupts</h2>
        <div class="run-list">{interrupts_html or '<p>No pending interrupts.</p>'}</div>
      </article>
      <article class="panel">
        <h2>Approval Gates</h2>
        <div class="run-list">{gates_html or '<p>No approval gates.</p>'}</div>
      </article>
      <article class="panel">
        <h2>Execution Evidence</h2>
        <pre>{evidence_preview}</pre>
      </article>
      <article class="panel">
        <h2>Run Detail</h2>
        <pre>{run_detail}</pre>
      </article>
      <article class="panel panel-wide">
        <h2>Agent State</h2>
        <pre>{agent_preview}</pre>
      </article>
      <article class="panel panel-wide">
        <h2>Report Preview</h2>
        <pre>{report_preview}</pre>
      </article>
    </section>
  </main>
</body>
</html>"""


def _render_feedback_form(interrupt: dict[str, Any]) -> str:
    interrupt_id = escape(str(interrupt.get("interrupt_id", "")))
    title = escape(str(interrupt.get("title", "Submit feedback")))
    state_version = escape(str(interrupt.get("active_state_version", "")))
    resume_token = escape(str(interrupt.get("resume_token", "")))
    return f"""
<form method="post" action="/workflow/feedback" class="stack">
  <input type="hidden" name="interrupt_id" value="{interrupt_id}">
  <input type="hidden" name="state_version" value="{state_version}">
  <input type="hidden" name="resume_token" value="{resume_token}">
  <input type="hidden" name="kind" value="clarification">
  <label>{title}</label>
  <textarea name="content" rows="3" placeholder="Provide the requested feedback"></textarea>
  <button type="submit">Submit Feedback</button>
</form>
"""


def _render_gate_form(gate: dict[str, Any], interrupt: dict[str, Any] | None) -> str:
    gate_id = escape(str(gate.get("gate_id", "")))
    state_version = escape(str((interrupt or {}).get("active_state_version", "")))
    resume_token = escape(str((interrupt or {}).get("resume_token", "")))
    return f"""
<form method="post" action="/workflow/gates/{gate_id}/approve" class="inline-form">
  <input type="hidden" name="state_version" value="{state_version}">
  <input type="hidden" name="resume_token" value="{resume_token}">
  <button type="submit">Approve Gate {gate_id}</button>
</form>
<form method="post" action="/workflow/gates/{gate_id}/reject" class="inline-form">
  <input type="hidden" name="state_version" value="{state_version}">
  <input type="hidden" name="resume_token" value="{resume_token}">
  <button type="submit">Reject Gate {gate_id}</button>
</form>
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
  <section class="grid">
    <article class="panel">
      <h2>Create Episode</h2>
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
        f'<a class="run-item{selected}" href="/?run_id={escape(run_id)}">'
        f"<strong>{escape(str(item.get('step_id', '-')))}</strong>"
        f"<span>{escape(str(item.get('status', 'unknown')))}</span>"
        f"<code>{escape(run_id)}</code>"
        "</a>"
    )


def _render_interrupt_item(item: dict[str, Any]) -> str:
    return (
        '<div class="run-item">'
        f"<strong>{escape(str(item.get('title', '-')))}</strong>"
        f"<span>{escape(str(item.get('kind', 'interrupt')))} / {escape(str(item.get('status', 'unknown')))}</span>"
        f"<code>{escape(str(item.get('interrupt_id', '-')))}</code>"
        "</div>"
    )


def _render_gate_item(item: dict[str, Any]) -> str:
    return (
        '<div class="run-item">'
        f"<strong>{escape(str(item.get('gate_id', '-')))}</strong>"
        f"<span>{escape(str(item.get('risk_level', 'normal')))} / {escape(str(item.get('status', 'unknown')))}</span>"
        f"<code>{escape(str(item.get('policy_reason', '-')))}</code>"
        "</div>"
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
.shell { max-width: 1440px; margin: 0 auto; padding: 32px 20px 48px; }
.hero { display: grid; grid-template-columns: 1.7fr 1fr; gap: 18px; align-items: stretch; margin-bottom: 20px; }
.eyebrow { text-transform: uppercase; letter-spacing: 0.16em; font-size: 0.74rem; color: var(--accent); }
h1, h2 { margin: 0 0 12px; font-weight: 700; }
h1 { font-size: clamp(2rem, 5vw, 4.5rem); line-height: 0.94; }
h2 { font-size: 1.2rem; }
.lede { color: var(--muted); max-width: 56ch; }
.hero-card, .panel { background: color-mix(in srgb, var(--paper) 88%, white); border: 1px solid var(--line); border-radius: 20px; box-shadow: var(--shadow); }
.hero-card { display: grid; gap: 16px; padding: 22px; }
.hero-card span { display: block; color: var(--muted); font-size: 0.82rem; margin-bottom: 4px; }
.hero-card strong { font-size: 1.2rem; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.panel { padding: 20px; }
.panel-wide { grid-column: 1 / -1; }
.stack { display: grid; gap: 10px; margin-bottom: 14px; }
.inline-form { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
textarea, input, select, button, .secondary { font: inherit; border-radius: 14px; }
textarea, input, select { width: 100%; border: 1px solid var(--line); background: rgba(255, 255, 255, 0.9); padding: 12px 14px; }
button, .secondary { border: none; background: var(--accent); color: white; padding: 11px 16px; text-decoration: none; cursor: pointer; }
.secondary { background: var(--accent-2); }
pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-family: "SFMono-Regular", "Cascadia Code", monospace; font-size: 0.9rem; background: rgba(216, 207, 194, 0.24); padding: 14px; border-radius: 16px; }
.run-list { display: grid; gap: 10px; }
.run-item { display: grid; gap: 4px; color: inherit; text-decoration: none; border: 1px solid var(--line); border-radius: 16px; padding: 12px 14px; background: rgba(255,255,255,0.72); }
.run-item.active { border-color: var(--accent); background: rgba(30, 107, 82, 0.08); }
@media (max-width: 980px) { .hero, .grid { grid-template-columns: 1fr; } }
"""
