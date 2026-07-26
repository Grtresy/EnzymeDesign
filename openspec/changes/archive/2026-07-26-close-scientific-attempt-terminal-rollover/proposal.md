## Why

The latest authorized non-`rNN` closure-stage diagnostic reached a valid
published report, co-terminal final response, immutable scientific-attempt
closure, and an exact open post-attempt scope, but the AOX terminal observer
still failed. The current correction recognizes only the zero-open portion of
the scope rollover; if Host finalization completes between the failed writer
registration and the follow-up classification read, the expected post-attempt
scope is misclassified as observer identity corruption.

The same evidence also leaves the source-bound closure notification pending.
If the observer race is fixed in isolation, the current master wake path would
invoke the model again after immutable closure even though the co-terminal
response is already persisted. Both seams must be closed before consuming
another one-use live authority.

## What Changes

- Make session-scoped mutation-writer admission one short atomic decision and
  distinguish zero-open/closed-during-registration coordination from ambiguous
  open-scope corruption without weakening writer fences.
- Add one Core-owned typed projection for the monotonic scientific-attempt
  scope handoff: closure rollover pending, exact post-closure scope open, or
  invalid topology.
- Make the AOX bounded observer coordinator accept both legal snapshots of the
  same rollover, retry only the short observer/barrier inside the original
  command deadline, and preserve every unrelated identity/scope error.
- Mechanically acknowledge only an exact immutable-closure notification whose
  co-terminal response and actor/session/task bindings already verify, without
  a second model turn or assistant response. Admission and ordinary
  `manual_resume` signals remain agent-driven.
- Preserve safe typed admission/rollover diagnostics in sealed failure
  evidence so future races can be proven directly without exposing authority,
  paths, or private writer metadata.
- Replace non-monotonic test doubles with deterministic and file-backed SQLite
  interleavings that exercise the actual attempt-scope seal, post-scope open,
  closure notification, and terminal barrier.
- Keep one-use authority, explicit runtime drain, task-terminal semantics,
  formal/non-`rNN` separation, immutable r59 evidence, and no hidden model/tool
  retry unchanged.

## Capabilities

### New Capabilities

- `scientific-attempt-terminal-rollover`: Defines one Core-owned typed read
  model and bounded observer coordination for the monotonic attempt-scope to
  post-attempt-scope transition.
- `scientific-closure-notification-settlement`: Defines exact, source-bound,
  no-model settlement of an already immutable scientific closure notification.

### Modified Capabilities

- `host-quiescence-sealing`: Makes session writer admission atomic and
  distinguishes expected closed admission from ambiguous scope cardinality.

## Impact

The change affects generic mutation writer registration in
`packages/openzyme-core`, scientific-attempt lifecycle/scope projection,
agent-runtime signal settlement, AOX runtime coordination and safe failure
projection in `apps/openzyme-host-api`, plus focused Core/Host tests. It also
synchronizes `docs/OpenZyme架构设计.md`, the relevant stable `docs/v3/`
runtime/scientific-attempt documents, and the closure-stage/AOX operator
evidence record.

No public V3 endpoint, database schema, provider/HPC behavior, task business
state, or formal acceptance rule is relaxed. The consumed prior authorities,
targets, MICU rows, and r59 source remain immutable and non-retryable. A fresh
non-`rNN` live diagnostic is permitted only after a clean validated commit and
a new one-use authority.
