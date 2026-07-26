## Why

The process-isolated attempt supervisor still equates every nonterminal mutation scope with a live local writer. Scientific terminal rollover now deliberately leaves one deterministic post-closure session scope open, so a fully completed closure-stage product path is incorrectly sealed as `attempt_child_runner_failed` even after every writer and descendant has retired.

## What Changes

- Separate process-local mutation settlement from product-level mutation-scope topology: the supervisor proves zero active writers, stable SQLite/root bytes, zero exit, and empty process group; Core projections prove whether an open scope is legal.
- **BREAKING** Upgrade newly produced live supervision frames and receipts to `@3`, replacing the ambiguous `quiescent` claim with a local-settlement handoff bound to a canonical mutation-authority snapshot digest.
- Recompute the bounded settlement snapshot in the parent after exact process-group retirement and reject any child/parent drift before reading or sealing normal evidence.
- Preserve `@1/@2` only for frozen offline evidence; current live composition and qualification require `@3` and never down-project `@3` into a legacy receipt.
- Bind closure-stage runtime parity to the supervisor's real contract digest and explicitly enumerate the versioned supervision repair without changing model, budget, timeout, browser, driver, or retry settings.
- Add typed safe failures and real SQLite regressions for legal post-closure scope handoff, active writers, malformed topology, and snapshot drift.
- Synchronize the main architecture and stable V3 scientific-attempt/process-supervision documentation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `live-attempt-supervision`: normal evidence will require versioned local mutation settlement and parent post-retirement revalidation rather than zero nonterminal mutation scopes.
- `host-quiescence-sealing`: distinguish scope quiescence/sealing from process-local writer retirement and bounded authority handoff.
- `scientific-attempt-terminal-rollover`: require evidence composition between the existing legal post-closure scope projection and independent process-retirement receipt.

## Impact

Affected code includes `aox_attempt_supervision.py`, live evidence/bundle validators, selected-chain compatibility projection, closure-stage parity/verification, Core mutation-authority projection helpers, focused Host/Core tests, `docs/OpenZyme架构设计.md`, and related `docs/v3/` stable documents. No SQLite migration, agent policy change, lane change, scientific calculation change, provider retry change, or reconstruction-state rewrite is required.
