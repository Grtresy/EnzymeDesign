# Public diagnostic sanitizer deterministic red evidence

Status: frozen pre-repair product evidence bound by baseline report
`sha256:277eafc5e0ad314d44d19f7274717a81b3a1f61437848f5f5f620bd9b2656e3a`.

## Classification

- profile: `local_single_process_file_sqlite@1`
- invariant: `boundary-scale.public-diagnostic-bounded-work`
- classification: `product_defect`
- automatic P0 trigger: `unbounded-progress`
- owner: `sanitize_public_diagnostic_text()` in `packages/openzyme-runtime/src/openzyme_runtime/public_diagnostics.py`
- stable reproducer: `boundary-scale.public-diagnostic-bounded-work`
- focused repair change: `bound-public-diagnostic-sanitizer-work`
- AOX effect: r48/live remains paused.

## Deterministic reproducer

```text
uv run pytest apps/openzyme-host-api/tests/architecture_qualification/scenarios/test_public_diagnostic_scale.py::test_public_diagnostic_sanitizer_has_bounded_work --rootdir=. -q -p no:cacheprovider
```

Three consecutive pre-repair runs produced the same bounded result:

```json
{"completed_within_deadline":false,"deadline_milliseconds":1500,"input_byte_length":65536,"raw_exit_code":-15,"retirement_proven":true}
```

The child emits a nonce-bound canonical readiness frame before entering the real
production sanitizer. The parent observes the exact PID, PGID, and process start
time, applies a 1.5-second completion deadline, then retires the group through
the bounded TERM/KILL/descendant-emptiness protocol. Every run exited by
`SIGTERM`, proved an empty descendant group, and recorded zero real external
effects. The input is a plain allowed ASCII scalar; it contains no locator,
credential, secret, or adversarial encoding.

## Root cause evidence

On a 16 KiB plain `a` scalar, isolated regex timing showed:

```text
_CREDENTIAL_URI_PATTERN.sub    1.230562 seconds
_CREDENTIAL_URI_PATTERN.search 1.242028 seconds
all other individual sub/search stages <= 0.0021 seconds
```

The pattern
`[a-z][a-z0-9+.-]*://[^\s/@:]*:[^\s/@]*@[^\s\"'<>]*`
restarts an unanchored variable-length scheme candidate at successive positions
of an otherwise valid long scalar. Both the replacement pass and the final
residual-safety search repeat that work. The sanitizer is called from scheduler,
runtime, harness, sandbox, projection, tool, and Host error paths, so the defect
can block progress exactly when the system is trying to expose a bounded public
diagnostic.

The repair must preserve existing redaction, determinism, and idempotence. It
must close the original 64 KiB process-deadline scenario and owner-focused
secret/URI regression tests without widening the deadline or replacing the
production sanitizer with a fixture.
