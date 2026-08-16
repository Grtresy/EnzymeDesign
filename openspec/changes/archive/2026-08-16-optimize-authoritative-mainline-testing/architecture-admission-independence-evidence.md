# Clean Architecture Admission Independence Evidence

Date: 2026-07-29

This is repository/operator evidence for OpenSpec Task 10.8. It does not start
an AOX attempt, authorize a live campaign, or provide scientific evidence.

## Disposable clean candidate

The current main-worktree file contents were overlaid onto a local clone at
`/tmp/openzyme-admission-candidate-r1` and committed only inside that disposable
clone:

- candidate commit:
  `3ef7be491693c7c44dc4fe2bb725dacaa275bdb3`
- candidate worktree before and after qualification:
  clean
- tracked diff digest:
  `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- tracked dirty paths:
  none
- untracked sources:
  none
- dependency environment:
  fresh candidate-local `.venv` from `uv sync --offline`

The temporary commit is not a commit in the main checkout and was not pushed.

## Existing full admission command

The unchanged two-argument qualification entry was invoked in `admission`
mode:

```bash
./scripts/check-v3-architecture-qualification.sh \
  admission \
  /tmp/openzyme-admission-candidate-r1-evidence
```

It published exactly one canonical report:

- path:
  `/tmp/openzyme-admission-candidate-r1-evidence/architecture-qualification-report.json`
- file SHA-256:
  `ab4ee12665b032f06d5d9dd5b4dcf1575282063a9cd1682b44495e24067136a8`
- schema:
  `openzyme_v3_architecture_qualification_report@1`
- payload digest:
  `sha256:b1a8304d19e60c1746b8c21a6745e903e0899406ff241308f4e446f804add5f8`
- profile:
  `local_single_process_file_sqlite@1`
- selection:
  full, thirteen canonical scenarios
- harness:
  pass
- invariants:
  all thirteen `satisfied`
- gaps / open P0:
  none
- result:
  `admission_eligible=true`
- external boundary:
  `external_effects_real=false`, `aox_live_started=false`

No mainline plan, qualification sidecar, test-gate receipt, or diagnostic
receipt was supplied to this command.

## Independent pure verification

The separately invoked existing verifier:

```bash
uv run python scripts/verify-v3-architecture-qualification.py \
  /tmp/openzyme-admission-candidate-r1-evidence/architecture-qualification-report.json \
  --repo-root /tmp/openzyme-admission-candidate-r1
```

recomputed the same payload digest and source commit and returned
`valid=true`, `admission_eligible=true`, with no rejection reasons.

## Existing AOX consumer compatibility

The production
`verify_aox_architecture_qualification_report()` consumer read the same report
and derived the unchanged closed receipt:

- schema:
  `aox_architecture_qualification_receipt@1`
- receipt digest:
  `sha256:b26176796be612df40c172fb2f895417d5442cf0e991c8779b32ce413b900883`
- report payload digest:
  `sha256:b1a8304d19e60c1746b8c21a6745e903e0899406ff241308f4e446f804add5f8`
- registry digest:
  `sha256:88c06ab65e1914af757b29d14fa8b27557738a389917c00646b161373d8e8ad2`
- test-manifest digest:
  `sha256:1c9931633a965f99e836d0c05897f5f7c0cd42b2c08e44db85ca756420bf2960`
- source commit:
  `3ef7be491693c7c44dc4fe2bb725dacaa275bdb3`

The focused AOX receipt adapter and admission fail-closed scenarios then passed
`5/5`:

```bash
uv run pytest -q \
  apps/openzyme-host-api/tests/test_aox_architecture_qualification.py \
  apps/openzyme-host-api/tests/architecture_qualification/scenarios/test_aox_admission.py
```

This proves that full clean architecture admission continues to use its own
command, canonical report schema, pure verifier, and AOX receipt consumer. The
test-gate implementation neither replaces nor upgrades that authority.
