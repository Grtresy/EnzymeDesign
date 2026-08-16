## Why

The canonical architecture baseline proves that the production public-diagnostic sanitizer cannot complete a plain 64 KiB allowed scalar within a 1.5-second isolated-process deadline; profiling localizes the growth to the unanchored credential-URI regex. Because this sanitizer runs throughout scheduler, harness, sandbox, projection, tool, and Host error paths, an ordinary diagnostic can block the very control-plane path meant to fail safely.

## What Changes

- Replace the quadratic credential-URI scan with a bounded-work implementation that only evaluates plausible URI candidates while preserving credential redaction.
- Preserve public diagnostic determinism, idempotence, private-path/secret/credential redaction, public URL normalization, and existing output values for current covered inputs.
- Add owner-focused long benign scalar, credential URI, mixed-content, encoded locator, and repeated-sanitization regressions.
- Close the frozen `boundary-scale.public-diagnostic-bounded-work` identity-bound process scenario without widening its deadline, changing its input, or bypassing the production sanitizer.
- Keep AOX/r48 paused until the full qualification matrix has zero open P0.

## Capabilities

### New Capabilities

- `public-diagnostic-safety`: Define bounded-work, deterministic, idempotent sanitization of public diagnostic text while retaining all private-data redaction requirements.

### Modified Capabilities

None.

## Impact

- Product code: `packages/openzyme-runtime/src/openzyme_runtime/public_diagnostics.py`.
- Owner-focused tests: `packages/openzyme-runtime/tests/test_public_diagnostics.py`.
- Architecture evidence: the existing public-diagnostic bounded-work scenario and P0 closure records.
- Stable architecture documentation: V3 public-interface and reliability diagnostic boundaries.
- No wire schema, persistence model, provider behavior, live external dependency, or user-visible unredacted diagnostic expansion.
