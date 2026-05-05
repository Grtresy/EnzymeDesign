# openzyme-host-cli

Thin CLI client for the V2 OpenZyme Host API.

## Scope

- Calls the Host HTTP API for workflow control and inspection
- Does not own a private runtime or direct graph invocation path
- Renders terminal-friendly workflow, run, artifact, and report summaries

## Examples

```bash
uv --project apps/openzyme-host-cli run openzyme projects list
uv --project apps/openzyme-host-cli run openzyme episodes create --project-id proj_001 --objective "Design a thermostable enzyme candidate"
uv --project apps/openzyme-host-cli run openzyme episodes show --episode-id ep_123
uv --project apps/openzyme-host-cli run openzyme episodes approve --episode-id ep_123
uv --project apps/openzyme-host-cli run openzyme episodes reports --episode-id ep_123
```

## Configuration

The CLI resolves defaults from flags first, then environment variables:

- `OPENZYME_HOST_BASE_URL`
- `OPENZYME_PROJECT_ID`
- `OPENZYME_EPISODE_ID`
