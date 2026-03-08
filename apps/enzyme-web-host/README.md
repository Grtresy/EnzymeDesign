# OpenZyme Web Host

Run the local browser host against an initialized project:

```bash
uv run enzyme-web-host --project-root /path/to/project
```

The server binds to a single project root, reads canonical workspace state through
`enzyme-host-runtime`, and exposes browser actions for:

- creating a new episode
- starting, continuing, and executing the host workflow
- resolving pending feedback items and approval gates
- viewing status, recent runs, run detail, backend provenance, and the current report

For development, the MVP uses a Python-only stack with FastAPI and server-rendered HTML.

## Backend provenance in the UI

When the host agent is configured to use the LLM sidecar, the home page now
shows:

- the current agent backend
- whether the workflow is `healthy`, `degraded`, or `blocked`
- whether heuristic fallback is currently active
- the latest sidecar/provider error summary

Provider, model, and sidecar version stay in the `Backend Details` panel instead
of taking over the main workflow controls.

If the UI shows `degraded`, the sidecar failed but the runtime finished the
current operation through heuristic fallback. If it shows `blocked`, fallback
was disabled and no tool action should execute until the backend issue is fixed.

## Sidecar setup

Install the Node sidecar once before using the LLM backend:

```bash
cd apps/pi-ai-sidecar
npm install
npm test
```

Project-local backend config lives at `.enzyme/agent_backend.json`, while
provider credentials remain in environment variables such as `OPENAI_API_KEY`.
