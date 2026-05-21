# openzyme-core

V3 harness control-plane foundations for OpenZyme.

## Scope

This package owns the first V3 canonical persistence layer for:

- `sessions`
- `tasks` and `task_dependencies`
- `lanes`
- `approval_requests`
- `inbox_messages`
- `memory_entries`
- `agent_members`
- `engine_invocations`

## Rules

- V3 control-plane truth lives here, not in LangGraph checkpoints.
- New V3 top-level semantics should land in `openzyme-domain.control_plane` and `openzyme-core`.
- Do not recreate graph-owned top-level workflow state; sessions, tasks, lanes, approvals, artifacts, reports, and runtime signals are canonical here.
