## 1. Bounded Sanitizer Implementation

- [x] 1.1 Add a fixed-width left scheme boundary to credential-URI detection so long benign scalars cannot restart the greedy scheme scan at successive characters
- [x] 1.2 Preserve sanitizer transformation order, stable redaction markers, full-input handling, deterministic output, and idempotence without a truncation or alternate-sanitizer fallback

## 2. Owner-Focused Regression Coverage

- [x] 2.1 Add a complete 64 KiB benign-scalar regression that remains unchanged without a wall-clock unit-test assertion
- [x] 2.2 Add long mixed credential-URI, existing locator/encoding, nested payload, and repeated-sanitization regressions proving redaction semantics remain closed
- [x] 2.3 Run the focused `openzyme-runtime` test suite and lint/static checks for the touched paths

## 3. Architecture Proof and Documentation

- [x] 3.1 Update `docs/OpenZyme架构设计.md` and the relevant `docs/v3/` public-interface/reliability documents with the bounded public-diagnostic boundary
- [x] 3.2 Re-run the frozen `boundary-scale.public-diagnostic-bounded-work` identity-bound process scenario and pure verifier without changing its input, child mode, deadline, budget, or oracle
- [x] 3.3 Record the closure evidence in the parent qualification change and keep AOX/r48 paused until the complete architecture gate is admissible
