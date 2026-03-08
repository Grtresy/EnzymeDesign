# enzyme-host-cli

`enzyme-host-cli` is the debug and automation surface for the shared host
runtime. The browser-based `enzyme-web-host` is now the main MVP operator entrypoint.

## Workflow command surface

From an initialized project workspace:

```bash
enzyme init demo-project
cd demo-project
enzyme new-episode "improve binding for substrate X"
enzyme workflow start
enzyme workflow execute
enzyme status --verbose
enzyme logs <run_id>
enzyme report
```

Supported commands:

- `enzyme init <name>`
- `enzyme new-episode "<goal>"`
- `enzyme workflow start`
- `enzyme workflow continue`
- `enzyme workflow execute`
- `enzyme workflow feedback <interrupt_id> "<content>"`
- `enzyme workflow interrupts`
- `enzyme workflow gates`
- `enzyme workflow approve-gate <gate_id>`
- `enzyme workflow reject-gate <gate_id>`
- `enzyme status [--verbose]`
- `enzyme logs <run_id>`
- `enzyme report`

## Backend provenance in CLI output

Workflow summaries and `status` now include:

- `Agent Backend`: `heuristic` or `llm-sidecar`
- `Backend State`: `heuristic`, `healthy`, or `degraded`
- `Fallback Active`: whether a sidecar failure forced a heuristic fallback
- `Sidecar Error`: the last normalized sidecar/provider error summary

Use `--verbose` to keep provider/model provenance in the terminal, including the
sidecar name/version when the LLM backend is active.

If `Backend State` becomes `degraded`, the workflow completed the current model
operation via heuristic fallback. If `Sidecar Error` is non-empty and fallback
is disabled, the episode status will become `blocked` until the sidecar config
or provider credentials are fixed.

## Sidecar backend setup

The shared runtime reads non-sensitive backend config from
`.enzyme/agent_backend.json`. Example:

```json
{
  "backend": "llm-sidecar",
  "llm_sidecar": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "timeout_seconds": 30,
    "allow_fallback": true
  }
}
```

Zhipu Coding Plan example for this runtime:

```json
{
  "backend": "llm-sidecar",
  "llm_sidecar": {
    "provider": "zhipu-coding",
    "model": "GLM-5",
    "api_style": "openai-compatible",
    "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
    "api_key_env": "ZHIPUAI_API_KEY",
    "timeout_seconds": 60,
    "allow_fallback": true
  }
}
```

Provider credentials are still injected through environment variables such as
`OPENAI_API_KEY` and are never read from the project config file.
The sidecar also normalizes common OpenAI-compatible function-call quirks
before schema validation.

## Local development

From the repo root:

```bash
cd apps/pi-ai-sidecar && npm install && npm test
uv --project apps/enzyme-host-cli sync --extra dev
uv --project apps/enzyme-host-cli run pytest
uv --project apps/enzyme-host-cli run enzyme --help
```
