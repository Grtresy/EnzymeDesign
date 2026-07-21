## 1. Supervision protocol and lifecycle primitives

- [x] 1.1 Implement canonical bounded lifecycle frames, exact identity/hash-chain validation, and closed normal/fatal schemas
- [x] 1.2 Implement the parent root-access gate, POSIX process identity/group inspection, and bounded TERM-to-KILL retirement ladder
- [x] 1.3 Implement append-only child-result sealing and separate parent-owned fatal evidence outside attempt roots

## 2. Process-isolated attempt runner

- [x] 2.1 Add a top-level spawn child entrypoint that owns the wrapped attempt runner, performs SQLite/root quiescence checks, and emits the terminal frame chain
- [x] 2.2 Add `ProcessIsolatedAttemptRunner` normal-path result verification and exact process-supervision receipt injection
- [x] 2.3 Add timeout, protocol-corruption, nonzero-exit, result-mismatch, and descendant-leak fatal handling without manufacturing product closure

## 3. Campaign and CLI integration

- [x] 3.1 Propagate typed supervision-fatal errors through the campaign without reading ledger-after or publishing a normal attempt bundle
- [x] 3.2 Require an exact supervision receipt for live bundle-producing attempts and validate it in offline attempt verification
- [x] 3.3 Wrap both positive and fault `run-live` attempts with fixed derived supervision bounds while preserving direct runner construction only as a non-live test seam

## 4. Regression and fault testing

- [x] 4.1 Test canonical frame validation, root-gate rejection, normal spawn completion, and result-digest binding
- [x] 4.2 Test stuck child TERM/KILL retirement, malformed/truncated protocol, child failure, and no partial attempt-bundle publication
- [x] 4.3 Test descendant retirement, fatal-artifact privacy/append-only semantics, unknown external outcome, and live CLI composition

## 5. Documentation and closure

- [x] 5.1 Update the architecture proposal and stable V3/cutover documentation to describe the implemented local POSIX boundary and explicitly split residual hardening
- [x] 5.2 Run focused host-api tests, strict OpenSpec validation, Ruff, the mainline gate, and repository consistency checks
- [x] 5.3 Verify the completed change, sync its delta spec, archive the completed proposal with OpenSpec, and leave the numbered live campaign paused for explicit operator confirmation
