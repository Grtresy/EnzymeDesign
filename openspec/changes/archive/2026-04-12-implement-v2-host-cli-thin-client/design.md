## Context

V2 currently exposes only the FastAPI Host and the browser demo. The repository guidelines and blueprint both expect a thin CLI client that shares Host semantics with the web surface, but the old CLI was moved into `legacy/v1`. Phase D needs a new CLI that is intentionally smaller and simpler than V1: it should speak HTTP to Host, format results for terminal use, and avoid owning any workflow state itself.

## Goals / Non-Goals

**Goals:**
- Create a V2 CLI app that can start, resume, approve, reject, and inspect episodes through Host API calls.
- Keep CLI command vocabulary aligned with the existing Host command/query surfaces.
- Provide useful terminal summaries for workflow, runs, artifacts, and reports without requiring raw JSON inspection.

**Non-Goals:**
- Reintroduce a local private runtime or direct graph invocation path in the CLI.
- Mirror every possible browser interaction in the first CLI release.
- Add deployment automation or shell-completion polish beyond what is needed for a functional thin client.

## Decisions

### Make the CLI a strict HTTP client over Host API

The CLI should call the FastAPI Host endpoints and render terminal-friendly output. This preserves the blueprint's shared-semantics rule and avoids rebuilding workflow logic in a second entrypoint.

Alternative considered: compile and invoke the graph directly from the CLI for local workflows. Rejected because it would recreate split runtime semantics.

### Optimize the first command surface for workflow control and inspection

The initial CLI should cover the core lifecycle: create episode, resume, resolve approval, show workspace, and inspect runs/artifacts/reports. That is enough to validate parity with the browser for operator workflows.

Alternative considered: build a full project-management CLI from the start. Rejected because it expands scope before the workflow control path is proven.

### Keep report output human-readable, with optional machine-readable fallback

CLI output should prioritize concise terminal summaries, while still allowing structured output modes where appropriate. This keeps the thin client useful for both humans and scripts without adding a second domain model.

Alternative considered: JSON-only output in the first version. Rejected because it would make the CLI harder to use interactively.

## Risks / Trade-offs

- [Risk] Host endpoint gaps may be discovered only once a second entrypoint consumes them. → Mitigation: treat missing query or command affordances as part of the CLI change and close them in Host rather than adding CLI workarounds.
- [Risk] Terminal UX can become inconsistent if each command shapes output differently. → Mitigation: define a small set of shared renderers for workflow summaries, pending actions, and record lists.
- [Risk] Streaming support may be overkill for the first CLI version. → Mitigation: make polling or one-shot queries sufficient initially unless a specific workflow requires live streaming.

## Migration Plan

Scaffold the new CLI app and shared Host client first, then implement lifecycle commands, then add read-only inspection commands and terminal rendering, and finally add end-to-end CLI tests against the local Host demo/runtime. The legacy V1 CLI remains untouched.
