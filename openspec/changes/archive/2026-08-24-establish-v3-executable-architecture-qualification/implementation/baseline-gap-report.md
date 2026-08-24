# V3 architecture qualification baseline GAP report

Status: derived human review summary; **not admission authority**.

The only authority for this baseline is the immutable canonical machine report
that was written outside the checkout and verified before this Markdown file was
created:

- report path at generation: `/tmp/openzyme-v3-qualification-baseline-r7-019f8648/architecture-qualification-report.json`
- payload digest: `sha256:277eafc5e0ad314d44d19f7274717a81b3a1f61437848f5f5f620bd9b2656e3a`
- exact command: `./scripts/check-v3-architecture-qualification.sh diagnostic /tmp/openzyme-v3-qualification-baseline-r7-019f8648`
- profile: `local_single_process_file_sqlite@1`
- source commit: `36331ad4f1dfd2a9a975bf62a01560662790b2d2`
- tracked diff digest: `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- untracked source manifest digest: `sha256:8ab02861333034ee58f29e33e232e4f18c1346ae03e4b20089193920975f418d`
- registry digest: `sha256:d5f7222fda2699f8d38f903ebad736b92c495b8b1ff0b7aae07e7bcbf6eff0c9`
- test-manifest digest: `sha256:8c7060c2014c114b3e225365d5c6a119056b12984fab9d30e85f79a67c189729`
- implementation digest: `sha256:97b9c1cc22264467598609e5071b44928a9980c0a6ef34b9253a9bdedbeff8e4`
- runner digest: `sha256:e44e7c6e0cafeb8be73ceda520df9243927be8f7497498d8b98be58585453a94`
- verifier digest: `sha256:3f47fa3ecc4a8a14cdfa698b4fa781e5421027240fea1376c24ac37558d33837`

The pure verifier returned a valid diagnostic result with
`admission_eligible=false`. Any later checkout change is expected to make that
historical report fail current-checkout verification; this summary does not
repair or replace that identity binding.

## Matrix result

- 11 registered stable scenarios executed with the complete `full` selection;
- 9 scenarios and their invariants were `satisfied`;
- 2 scenarios and their invariants were `violated`;
- 0 scenarios or invariants were `unproven`;
- harness self-tests passed;
- `external_effects_real=false` and `aox_live_started=false`;
- no qualification, fault-child, or scenario process remained after the run.

## Confirmed GAPs

### P0: durable supervisor counts non-progress as progress

- invariant: `supervisor-progress.semantic-progress`
- scenario: `supervisor-progress.semantic-progress-only`
- classification: `product_defect`
- owner: `durable-work-supervisor`
- observed trigger: `unbounded-progress`
- machine evidence digest: `sha256:98af24b6272df59a798d0bd5106b140ec1735798557a4634b27e73787b4dbeea`
- frozen detail: `implementation/supervisor-no-progress-red.md`

The real production supervisor emits one immediate notification for each
unchanged poll and reconcile tick. Canonical state/effect/event evidence is
complete, so this is not a fixture or oracle gap. The focused repair change is
`fix-v3-durable-supervisor-semantic-progress`.

### P0: public diagnostic sanitizer has unbounded accepted-input work

- invariant: `boundary-scale.public-diagnostic-bounded-work`
- scenario: `boundary-scale.public-diagnostic-bounded-work`
- classification: `product_defect`
- owner: `public-diagnostic-sanitizer`
- observed trigger: `unbounded-progress`
- machine evidence digest: `sha256:2f7d9e61505accecdb71898d6600ac3146c7e6c2d68939c2bf14044b40552197`
- frozen detail: `implementation/public-diagnostic-scale-red.md`

The production sanitizer did not finish a 64 KiB allowed scalar within the
1.5-second child deadline in three consecutive runs. Exact process identity,
SIGTERM exit, descendant emptiness, zero real external effect, and a canonical
probe digest were preserved. Component profiling localizes the growth to
`_CREDENTIAL_URI_PATTERN`. The focused repair change is
`bound-public-diagnostic-sanitizer-work`.

## Explicit non-GAP finding

`operator-retirement.idempotent-in-doubt-stop` passed both in the complete
machine run and in a separate focused rerun. Its report record binds one
observation digest and two effect-ledger digests, reports no real external
effect, and proves retirement of all child groups. It therefore does not trigger
a proposal merely because it was selected for priority review.

No `qualification_defect`, `declared_profile_limitation`, or
`deferred_enhancement` remains in this baseline. Both confirmed P0s block
admission and AOX r48/live. Their red scenarios, budgets, and production
composition must remain unchanged through repair.
