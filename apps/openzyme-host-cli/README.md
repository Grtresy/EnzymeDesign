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
uv --project apps/openzyme-host-cli run openzyme runtime health
```

## Public evidence receipts

Codex-conducted AOX tests use the same thin public client. `--receipt-chain` appends one canonical
`openzyme_public_api_receipt@2` JSONL record for every Host response, including non-2xx responses;
`--seal-response` publishes the current semantic response once and requires the same receipt chain.
Neither option drives runtime or interprets business terminal state.

```bash
uv --project apps/openzyme-host-cli run openzyme \
  --receipt-chain /absolute/private/receipts.jsonl \
  --seal-response /absolute/private/final-evidence.json \
  scientific export-evidence \
  --session-id sess_123 \
  --attempt-id attempt_123 \
  --selection-id selection_123
```

The public conductor can also seal one-shot `sessions events`, `approvals pending`, workspace,
runtime-command status and approval-resolution responses. Receipt storage must be an existing real
private directory; the chain is continuous, locked and fsynced, while sealed responses are
no-replace. These are evidence facts, not authority to approve or continue a run.

## Configuration

The CLI resolves defaults from flags first, then environment variables:

- `OPENZYME_HOST_BASE_URL`
- `OPENZYME_HOST_AUTH_TOKEN`（shared Host 的 Bearer token；CLI 对 mutation 自动生成 `Idempotency-Key`）
- `OPENZYME_PROJECT_ID`
