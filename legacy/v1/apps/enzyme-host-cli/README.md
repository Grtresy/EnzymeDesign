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

## Decision summary in CLI output

Default workflow and `status` output now prioritizes:

- `Workflow Status`
- `Summary`
- `Current Focus`
- `Why It Stopped`
- `Next Step`
- whether the user needs to act now

Detailed mode keeps the same top summary, then adds:

- `Technical Explanation`
- selected action policy reason and trust decision
- pending interrupt technical detail
- pending gate trust / policy context

The stop reasons exposed by the shared runtime are:

- `completed`
- `failed`
- `needs_input`
- `awaiting_approval`
- `blocked`
- `max_turns_exceeded`
- `escalated`

The first release does not expose ETA. The CLI only shows actionable progress.

## Project trust policy

Workflow budget and trust policy are configured in `enzyme.yaml`, not in the
CLI flags. Example:

```json
{
  "host": {
    "workflow_budget": {
      "max_decision_rounds": 6,
      "max_auto_actions": 3
    },
    "trust_policy": {
      "rules": [
        {
          "tool": "vina",
          "decision": "approval",
          "risk_level": "high",
          "policy_reason": "Docking jobs must be approved before remote execution.",
          "plain_language_reason": "这是高成本远程计算，执行前需要你确认。",
          "trust_decision": "approval_required",
          "rule_id": "project:vina-approval"
        }
      ]
    }
  }
}
```

## Decision summary semantics

Default `workflow` and `status` output now leads with a shared runtime summary:

- `Workflow Status`: canonical stop reason such as `completed`, `needs_input`,
  `awaiting_approval`, `blocked`, `max_turns_exceeded`, or `escalated`
- `Summary`: plain-language Chinese explanation for what happened
- `Current Focus`: what the host is doing or waiting on right now
- `Why It Stopped`: the current blocker or pending approval/input
- `Next Step`: the recommended human action
- `Needs User Action`: whether the user should intervene immediately

Use `--verbose` to add the technical explanation, selected-action policy
reasoning, trust decision, and the most relevant current observation.

Practical guidance:

- If the CLI shows `needs_input`, answer the pending question first.
- If it shows `awaiting_approval`, approve, reject, or tighten constraints.
- If it shows `max_turns_exceeded`, give the host narrower inputs or specify
  the next action manually.
- If it shows `escalated`, the runtime is explicitly asking for human takeover.

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

## Project trust policy and workflow budget

Decision semantics live in the project config file `enzyme.yaml`, not in the
sidecar backend config. Example:

```json
{
  "project": {
    "id": "demo-project",
    "name": "demo-project",
    "created_at": "2026-03-15T00:00:00+00:00"
  },
  "host": {
    "workflow_budget": {
      "max_decision_rounds": 6,
      "max_auto_actions": 3
    },
    "trust_policy": {
      "default_decision": "allow",
      "default_plain_language_reason": "这是低风险动作，当前策略允许系统直接继续。",
      "rules": [
        {
          "tool": "vina",
          "decision": "approval",
          "plain_language_reason": "这是高成本远程计算，执行前需要你确认。",
          "policy_reason": "Docking uses remote or cost-amplifying resources.",
          "trust_decision": "approval_required",
          "rule_id": "project:vina-approval"
        }
      ]
    }
  }
}
```

The runtime writes the resulting stop reason, progress summary, plain-language
explanation, technical explanation, and trust-policy decision into canonical
episode state so Web Host and CLI always read the same fields.

## Local development

From the repo root:

```bash
cd apps/pi-ai-sidecar && npm install && npm test
uv --project apps/enzyme-host-cli sync --extra dev
uv --project apps/enzyme-host-cli run pytest
uv --project apps/enzyme-host-cli run enzyme --help
```
