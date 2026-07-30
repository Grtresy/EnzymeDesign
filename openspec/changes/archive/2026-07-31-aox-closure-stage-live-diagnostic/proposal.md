> **2026-07-31 retirement note:** this change is a completed historical
> diagnostic record. r65 Phase 2 removed its production authority, source
> qualification, reconstruction, live runner, CLI and dedicated runnable tests
> because the sealed historical state cannot satisfy the current source-bound
> finalization/close contract and can never enter formal acceptance. Historical
> SQLite compatibility, sealed evidence verification and the formal
> non-adoption negative gate remain. The delta spec below is not synced into
> current main specs as an active capability.

## Why

r59 proved the expensive scientific path through a valid healthy-empty result, a sealed
selection, and a published report, but its final lifecycle handoff failed before closure.
Re-running the entire numbered campaign would spend provider/HPC/MICU authority on already
observed science and would still make it hard to isolate whether the corrected
executor/reporter/master closing sequence works.

## What Changes

- Add a separately named, diagnostic-only AOX closure-stage live mode that starts from a
  fresh isolated root representing the canonical product state immediately before r59's
  erroneous execution-task terminal exit.
- Bind every reconstructed row and copied byte to a closed source/transformation manifest;
  leave the original r59 authority, roots, SQLite, artifacts, reports, browser receipts, and
  evidence immutable and never treat the diagnostic copy as adoption or formal acceptance.
- Reuse the production MICU model factory, runtime drain, mutation-writer/lease fencing,
  AOX tool and assistant-response preconditions, process supervision, token ledger, public
  API observation, and evidence-safety boundaries used by numbered runs.
- Exercise only the remaining agent-authored lifecycle: executor `completed` handoff,
  reporter/master reconciliation, explicit scientific-attempt closure with co-terminal final
  response, writer retirement, Host finalization, and bounded terminal convergence.
- Give the run a non-`rNN` identity and a schema-disjoint diagnostic receipt that cannot
  enter the formal exact-three plan, attempt bundle, campaign reducer, or GO decision.
- Fail closed before MICU if the source snapshot, reconstructed canonical state, current
  code/config/workflow identity, ledger, or expected pre-close readiness cannot be proven.

## Capabilities

### New Capabilities

- `aox-closure-stage-live-diagnostic`: Defines source-state qualification, fresh-root
  reconstruction, real-MICU lifecycle execution, process/ledger supervision, diagnostic
  evidence, and permanent non-acceptance isolation for the AOX closure-stage test.

### Modified Capabilities

None. Existing formal acceptance, diagnostic full-path, and generic live-attempt
supervision requirements remain unchanged.

## Impact

The change affects the AOX cutover CLI/live driver and adds a narrowly scoped
closure-stage diagnostic authority, reconstruction, runner, evidence/verifier, and tests.
It also updates the main architecture and relevant `docs/v3/` operator/scientific-attempt
contracts. No public V3 product endpoint or formal cutover acceptance schema is relaxed;
the live run consumes the configured MICU ledger and therefore requires the same explicit
operator authority and clean committed configuration boundary as existing live modes. The
pre-existing path-and-config-pinned cumulative ledger may remain at the numbered-run
ignored checkout location; it is not a fresh diagnostic output and cannot be relocated
without breaking runtime parity.
