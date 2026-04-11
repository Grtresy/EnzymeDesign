# enzyme-host-runtime

Shared host runtime services for OpenZyme CLI and Web surfaces.

## Decision Experience State

The runtime now writes a structured decision summary into canonical agent state
and the top-level episode `state.json`. The shared fields are meant to answer:

- what the workflow is doing now
- why it stopped
- what the user should do next
- whether the user needs to intervene immediately

The stable stop reasons are:

- `completed`
- `failed`
- `needs_input`
- `awaiting_approval`
- `blocked`
- `max_turns_exceeded`
- `escalated`

Each snapshot also includes:

- `progress_summary`
  - `current_focus`
  - `recent_completed`
  - `current_blocker`
  - `waiting_on`
  - `next_step`
  - `needs_user_intervention`
- `plain_language_explanation`
  - fixed to Chinese in the first release
- `technical_explanation`
- `next_step_suggestion`

The first release intentionally does not provide ETA or percentage-complete
fields. The runtime only emits actionable progress.

## Project-Level Workflow Budget

Workflow budget defaults live in `enzyme.yaml` and can be tuned per project:

```json
{
  "project": {
    "id": "demo-project",
    "name": "demo-project"
  },
  "host": {
    "workflow_budget": {
      "max_decision_rounds": 6,
      "max_auto_actions": 3
    }
  }
}
```

When the automatic budget is exhausted, the workflow stops with
`max_turns_exceeded` and suggests a concrete next step instead of looping.

## Project-Level Trust Policy

Project trust policy also lives in `enzyme.yaml`:

```json
{
  "host": {
    "trust_policy": {
      "default_decision": "allow",
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

The runtime records policy results even when the action is auto-allowed, so Web
and CLI can explain both:

- why approval is required
- why the action is blocked
- why the action can continue automatically
