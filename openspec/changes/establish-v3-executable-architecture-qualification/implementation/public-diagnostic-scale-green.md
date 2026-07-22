# Public diagnostic sanitizer focused green evidence

Status: pre-commit focused closure evidence; **not admission authority**.

This record closes the deterministic product defect observed in
`implementation/public-diagnostic-scale-red.md` for the current dirty checkout.
It does not close the remaining supervisor P0, prove a clean source commit, or
authorize AOX r48/live.

## Repair identity

- focused change: `bound-public-diagnostic-sanitizer-work`
- owner: `sanitize_public_diagnostic_text()` in
  `packages/openzyme-runtime/src/openzyme_runtime/public_diagnostics.py`
- implementation: add a fixed-width negative left boundary before a credential
  URI scheme candidate; transformation order, replacement values, and full
  input handling remain unchanged
- no truncation, alternate sanitizer, fixture simplification, registry edit,
  scenario deselection, skip/xfail, budget change, or deadline widening

## Owner-focused verification

```text
uv run pytest packages/openzyme-runtime/tests/test_public_diagnostics.py -q
```

Result: `111 passed`.

```text
uv run ruff check packages/openzyme-runtime/src/openzyme_runtime/public_diagnostics.py packages/openzyme-runtime/tests/test_public_diagnostics.py
```

Result: `All checks passed!`.

The owner suite now preserves the complete `64 * 1024` byte benign scalar,
redacts a credential URI after a 64 KiB benign prefix, preserves encoded/private
locator behavior in nested payloads, and proves repeated sanitization is
byte-stable.

## Original scenario and immutable diagnostic report

The frozen original scenario passed directly:

```text
uv run pytest apps/openzyme-host-api/tests/architecture_qualification/scenarios/test_public_diagnostic_scale.py -q
```

Result: `1 passed`.

The complete registered diagnostic selection was then run without changing the
scenario, registry, child mode, 64 KiB input, 1.5-second deadline, budget, or
oracle:

```text
./scripts/check-v3-architecture-qualification.sh diagnostic /tmp/openzyme-v3-qualification-sanitizer-closure-r1-019f8648
```

- report path at generation:
  `/tmp/openzyme-v3-qualification-sanitizer-closure-r1-019f8648/architecture-qualification-report.json`
- payload digest:
  `sha256:ae4d784719af50069c6fbc339758359233de534a44a8426f93f892561ff398fe`
- source commit: `36331ad4f1dfd2a9a975bf62a01560662790b2d2`
- tracked diff digest:
  `sha256:8c68c6cf26dfd5d1ede6eb47c2ada16ab9b309f5f92a51bd45a5760805656655`
- untracked manifest digest:
  `sha256:dd4b795ca1f57985d1d32c2316bede64a2b99831538056234f4c6bec53c8e3ec`
- registry digest:
  `sha256:d5f7222fda2699f8d38f903ebad736b92c495b8b1ff0b7aae07e7bcbf6eff0c9`
- test-manifest digest:
  `sha256:e8673150891b325c2f0c46a0d731578dbff22dcb833980cebecd145579e2707f`
- implementation digest:
  `sha256:97b9c1cc22264467598609e5071b44928a9980c0a6ef34b9253a9bdedbeff8e4`

The pure verifier independently accepted the report and returned the same
payload digest. It correctly retained `admission_eligible=false` because this
was diagnostic mode on a dirty checkout and the supervisor P0 remains open.
Creating this derived Markdown record changes the current untracked-source
manifest, so the historical report is expected to fail a later
current-checkout source-identity comparison; the report was verified before
this file was created.

## Closed invariant evidence

- invariant: `boundary-scale.public-diagnostic-bounded-work`
- invariant status: `satisfied`
- invariant evidence digest:
  `sha256:9dee1401133802947c23b5d95c7d98ddb4b3a0871da922623782c5c3a583b49a`
- scenario status: `pytest_outcome=pass`, `qualification_status=satisfied`
- scenario duration: `858 ms`
- observation digest:
  `sha256:6437fd2ea30dfc2ed9eab5c5aac1476e92bd777b4ad265765771e6b53815d477`
- execution-ledger digest:
  `sha256:f25024a6d5fbef5359ac89120b6060202f1e0570494d505234bbbefd0e6932a7`
- effect-ledger digest:
  `sha256:b412a765732b179c056a52a0c224c23d3fb681ec4f794ad84b328561e1ae91f2`
- `budget_exceeded=false`, no failure digest, no observed P0 trigger,
  `external_effects_real=false`, `aox_live_started=false`

The same report leaves exactly one open P0:
`p0.supervisor-progress.semantic-progress`. Therefore the sanitizer P0 is
focused-green, but the parent qualification change and AOX/r48 remain blocked
on the supervisor repair and a later full zero-P0 admission cycle.
