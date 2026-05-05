# V3 Rollback Strategy

## Rollback Principle

Rollback returns traffic to the frozen V2 path without deleting V3 control-plane data. V3 state is preserved for diagnosis and later replay; rollback is a routing and feature-exposure decision, not a destructive migration.

## Triggers

- V3 deterministic eval fails on the release candidate.
- Live V3 task-plan smoke repeatedly fails with configured live providers.
- `/v3` workspace projection omits task, approval, engine, artifact, report draft, or report data required by the UI.
- Execution approval resolution cannot recover to a completed or diagnostically actionable state.
- Report publishing cannot produce a final report for a completed workspace.

## Immediate Actions

1. Disable V3 as the default UI/CLI entry point.
2. Keep `/v3` endpoints read-accessible for diagnosis when possible.
3. Route new user workflows back to the V2 API path.
4. Capture the affected V3 session ids, event replay, pending approval ids, LLM debug records, and eval summary.
5. Stop adding new product behavior until the failed V3 invariant is fixed and verified.

## Data Handling

- Do not delete V3 sessions, task board items, lanes, approvals, memory, engine invocations, artifacts, report drafts, or reports during rollback.
- V2 does not become the owner of V3 control-plane state.
- If a user needs continuity, create a fresh V2 workflow using the visible V3 objective and latest report/workspace summary as input.
- After recovery, V3 sessions may be replayed or inspected, but automated V3-to-V2 state mutation is out of scope for this cutover.

## Recovery Requirements

- Add or update a deterministic regression test for the failure.
- Run `uv run python -m openzyme_host_api.evals --v3`.
- Run the scoped pytest command covering the changed app/package.
- Run `./scripts/check-mainline.sh` before re-enabling V3 as a default entry point.

## Rollback Exit

V3 may be re-enabled only after the original trigger has a passing regression, deterministic V3 eval passes, and the owner has reviewed the event replay from the failed session.
