## Context

The frozen architecture-qualification baseline
`sha256:277eafc5e0ad314d44d19f7274717a81b3a1f61437848f5f5f620bd9b2656e3a`
reproduces a P0 `unbounded-progress` failure in an identity-bound child process.
Three consecutive invocations of the production
`sanitize_public_diagnostic_text()` on a plain 64 KiB allowed scalar exceed the
registered 1.5-second hard deadline and are forcibly retired with no leaked
descendants or external effects.

Profiling localizes almost all time to `_CREDENTIAL_URI_PATTERN`: the unanchored
`[a-z][a-z0-9+.-]*://...` expression retries a long greedy scheme candidate at
successive starting positions when `://` is absent. Public diagnostic
sanitization is used across scheduler, harness, sandbox, projection, tools, and
Host error paths, so its failure mode can block control-plane error handling.

## Goals / Non-Goals

**Goals**

- Make credential-URI detection bounded for accepted diagnostic scalar sizes.
- Preserve existing redaction, determinism, idempotence, and public URL
  normalization behavior.
- Keep the full input available to the existing sanitizer pipeline; do not hide
  the complexity defect by pre-truncating the value.
- Close the original identity-bound scale scenario without changing its input,
  deadline, child mode, or oracle.

**Non-Goals**

- Expanding public diagnostic content or weakening secret/private locator
  detection.
- Changing API payload bounds, persistence, provider behavior, or raw private
  diagnostic storage.
- Promising arbitrary-size or adversarial-regex service beyond the explicit
  accepted scalar bounds and executable qualification profile.
- Resuming AOX/r48 before the full qualification gate is clean.

## Decisions

### 1. Add a left boundary to credential-URI candidate matching

The credential URI expression will require that the scheme candidate start at
the beginning of the scalar or immediately after a character that cannot be a
scheme character. The boundary is a fixed-width negative lookbehind, while the
remaining credential and locator grammar stays unchanged.

For a long benign alphabetic scalar, only the first position can start a scheme
candidate; later positions fail the constant-width boundary rather than each
rescanning the suffix. A URI following whitespace, `=`, punctuation, or another
non-scheme delimiter remains discoverable. A contiguous leading scheme token
continues to match from its true start.

This minimal expression change was selected over a separate parser because it
preserves the current match/replacement surface and composes with the remaining
sanitization stages. A simple `"://" in value` prefilter alone was rejected: it
fixes the measured benign case but does not bound repeated candidate restarts in
mixed content.

### 2. Do not truncate inside the sanitizer

Callers already own their public payload-size limits. The sanitizer will process
the supplied scalar and return its deterministic redacted form. Silent
pre-truncation could discard a secret located after the cut and would make the
qualification scenario pass without repairing the unsafe scan.

### 3. Preserve transformation order and idempotence

The credential-URI stage remains in its current order relative to bearer,
authorization, key/value, private locator, encoded locator, path, and HTTP URL
sanitization. Existing replacement markers remain stable, and sanitizing an
already sanitized value returns the same value.

### 4. Use semantic and hard-deadline regressions together

Owner-focused runtime tests will cover a long benign scalar, a long mixed scalar
with a credential URI, existing private/encoded locators, and repeated
sanitization without relying on a flaky micro-benchmark. The frozen
`boundary-scale.public-diagnostic-bounded-work` child-process scenario remains
the hard deadline and retirement proof.

## Risks / Trade-offs

- **Regex-engine behavior varies by platform:** the fixed boundary removes the
  repeated greedy restart responsible for the baseline. The architecture child
  process, rather than a unit-test timing assertion, remains the acceptance
  proof on the supported profile.
- **Unusual embedded schemes:** the boundary follows RFC-style scheme
  characters. Existing strings whose apparent scheme begins inside another
  contiguous valid scheme token are still treated as one scheme token, matching
  prior behavior.
- **Future regex additions can reintroduce unsafe work:** new sanitizer patterns
  must receive long benign/mixed owner tests and pass the registered scale
  scenario.

## Migration Plan

1. Add owner-focused semantic regressions that include 64 KiB benign and mixed
   values.
2. Add the fixed-width scheme boundary to the production credential-URI
   expression without changing replacement markers or transformation order.
3. Run runtime tests, the frozen boundary-scale scenario, and the pure evidence
   verifier.
4. Update stable V3 public-interface/reliability documentation in the same
   slice.
5. Roll back by reverting the expression and tests together; no persisted data
   or wire migration is involved.

## Open Questions

None. The frozen input and deadline provide the executable acceptance boundary.
