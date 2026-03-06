# Enzyme Web Host

Run the local browser host against an initialized project:

```bash
uv run enzyme-web-host --project-root /path/to/project
```

The server binds to a single project root, reads canonical workspace state through
`enzyme-host-runtime`, and exposes browser actions for:

- creating a new episode
- confirming or importing a plan JSON document
- running the full plan, resuming, or running a selected step
- viewing status, recent runs, run detail, and the current report

For development, the MVP uses a Python-only stack with FastAPI and server-rendered HTML.
