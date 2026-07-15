# openzyme-host-cli

Thin CLI client for the OpenZyme V3 Host API.

## Scope

- Calls the Host HTTP API for session, task, lane, and approval control
- Does not own a private runtime
- Renders terminal-friendly V3 workspace summaries

## Examples

```bash
uv --project apps/openzyme-host-cli run openzyme sessions create --project-id proj_001 --session-id sess_123 --objective "Design a thermostable enzyme candidate"
uv --project apps/openzyme-host-cli run openzyme sessions show --session-id sess_123
uv --project apps/openzyme-host-cli run openzyme sessions message --session-id sess_123 --message "Create a research task"
uv --project apps/openzyme-host-cli run openzyme tasks create --session-id sess_123 --subject "Collect evidence"
```

## Configuration

The CLI resolves defaults from flags first, then environment variables:

- `OPENZYME_HOST_BASE_URL`
- `OPENZYME_HOST_AUTH_TOKEN`（shared Host 的 Bearer token；CLI 对 mutation 自动生成 `Idempotency-Key`）
- `OPENZYME_PROJECT_ID`
