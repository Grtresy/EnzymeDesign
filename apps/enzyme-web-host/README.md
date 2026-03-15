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

## Decision summary in the main view

The browser home page now prioritizes a shared decision summary from runtime,
instead of asking users to infer state from raw JSON:

- current workflow status
- why the workflow stopped
- what the user should do next
- whether immediate user intervention is recommended
- recent completed milestones

The main panel uses Chinese plain-language explanation. Technical explanation
and policy detail stay in the debug area.

The stable stop reasons surfaced by the runtime are:

- `completed`
- `failed`
- `needs_input`
- `awaiting_approval`
- `blocked`
- `max_turns_exceeded`
- `escalated`

## Decision-first UI

The main workflow area now prioritizes:

- the canonical `Workflow Status`
- the plain-language explanation of why the host stopped or what it selected
- the current blocker or pending approval/input
- the recommended next step
- whether the user should intervene immediately

Technical details stay in the debug section so the first screen answers two
operator questions quickly: "why did the system stop?" and "what should I do
next?"

Current stop reasons include `completed`, `needs_input`, `awaiting_approval`,
`blocked`, `max_turns_exceeded`, and `escalated`.

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

## Project trust policy and workflow budget

The Web Host reads trust policy and decision budget from `enzyme.yaml`. Example:

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

The first release does not show ETA. The UI only presents actionable progress
and next-step guidance.

The UI reads the same canonical progress summary and explanation fields that the
CLI uses:

- `progress_summary.current_focus`
- `progress_summary.recent_completed`
- `progress_summary.current_blocker`
- `next_step_suggestion`
- `plain_language_explanation`
- `technical_explanation`

## Sidecar setup

Install the Node sidecar once before using the LLM backend:

```bash
cd apps/pi-ai-sidecar
npm install
npm test
```

Project-local backend config lives at `.enzyme/agent_backend.json`, while
provider credentials remain in environment variables such as `OPENAI_API_KEY`.

Workflow budget and trust-policy rules are configured in `enzyme.yaml` under the
`host` section. That is where project-specific rules can require approval,
auto-allow low-risk actions, or block specific tools with a human-readable
reason that will appear in both Web Host and CLI.
