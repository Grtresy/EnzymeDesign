# Optimized Mainline Authority Cutover Evidence

Date: 2026-07-29

Status: authority cutover, first fixed-four authoritative run, same-contract
forced-serial run, and independent pure receipt verification are complete.

This is repository/operator evidence only. The current authority is
`scripts/check-mainline.sh`, and it proves only the complete non-live merge
gate. Both receipts remain `admission_eligible=false` and
`live_eligible=false`; neither can satisfy architecture admission, AOX launch,
live-campaign, or scientific-evidence consumers.

## Cutover prerequisites

- The user explicitly agreed:
  `同意使用这 20-case immutable replay corpus`.
- The agreed corpus and legacy/optimized parity are recorded in
  `replay-corpus-evidence.md`.
- Five-pair performance acceptance had already proven fixed-four cold/warm
  reductions of `39.94% / 40.17%` with maximum orchestration overhead
  `2.202%`.
- The old sequential commands remain executable only through
  `scripts/check-mainline-legacy.sh`, whose start and completion messages both
  disclaim current authority.

## Current fixed-four authority

Command:

```bash
./scripts/check-mainline.sh
```

Raw checkout-external evidence:

- root:
  `/tmp/openzyme-mainline-authoritative.CEPPvQ/evidence`
- source identity:
  `sha256:c2aa89924941dff9b96830e40a7ea7835bbcc69e49c711704f4f1ff6febb942a`
- canonical plan digest:
  `sha256:aa5d618ec0c1a1a5a572daa6311c22bf1a9187454900a4b8796a6abc541e6818`
- plan file SHA-256:
  `c12e276a3f6d23502b88e4698e632f785d9db768018d2cb45892f121d0c22142`
- canonical receipt digest:
  `sha256:d1d98d43c79da08092cf625b3bfe177465ef25222fc6d96ea221af596220a6b0`
- receipt file SHA-256:
  `5eb5ff7cb4f93f7127c099389af7f19deb756907247827245a180f525c926637`
- canonical qualification report payload digest:
  `sha256:36884f60d9055a257046c1755f3eb50ba3e8336ba605313a1c56d219bd6dd028`
- qualification report file SHA-256:
  `06fd56ede52bb2e7ef9b95a6e469a407a33ce4be2f7bee3ced5e6ba7f838cac4`
- receipt total:
  `256.877013456 s`
- result:
  terminal pass; wrapper-level separate
  `verify-mainline-authoritative` pass

The receipt closes `2,817 / 2,817 / 2,817`
collected/executed/result nodes with zero unexpected deselection. Architecture
qualification owns and verifies `84` harness plus `13` selected scenario
nodes. Source Ruff, audit Ruff, compatibility semantic audit, qualification,
general residual, Web UI test, and Web UI build all ran in fail-fast order and
passed. The plan records fixed `workers=4`, hard maximum `4`,
`distribution=loadfile`, and unclassified default `serial_unknown`.

## Same-contract forced serial

Command:

```bash
./scripts/check-mainline.sh --forced-serial
```

Raw checkout-external evidence:

- root:
  `/tmp/openzyme-mainline-authoritative.mtLJyY/evidence`
- source identity:
  `sha256:e7cfa0a97af644ee991b64ac28508fe33b6419d818924415503abdbe45e748bd`
- canonical plan digest:
  `sha256:be435444747e1f070c9293a798bd4dd8112121527059106d1d871cee0fc98372`
- plan file SHA-256:
  `05638a442ac8b46b8d98d5cbde6f3fe94515048774de0911b699437fd1e37cbe`
- canonical receipt digest:
  `sha256:49a0e2a460756c5804b8a3f37a969f7ad0438d819e77ed16b8b1cce3775c603f`
- receipt file SHA-256:
  `2b44a79ceb02991c093785e89545294d32325efeb360a26418d2fcdfeb249e01`
- canonical qualification report payload digest:
  `sha256:4c50fc822395ec2155acb18cbd457daebb14142e9f9c1510ea6009f0398cd00e`
- qualification report file SHA-256:
  `f422ec7c9ac48a01e0fd106b22a46b5395b20bbe2aa355b70e235bc72aca2556`
- receipt total:
  `393.331745061 s`
- result:
  terminal pass; wrapper-level separate
  `verify-mainline-authoritative` pass

The forced-serial receipt also closes
`2,817 / 2,817 / 2,817`, zero unexpected deselection, qualification
`84 + 13`, and both required frontend stages. Its only scheduler change is
`workers=1` and `mode=forced_serial`.

## Exact comparison

The comparison removes only invocation id, checkout-external output paths,
source identity, worker mode/count, and timing. It retains:

- config and planner digests;
- expected coverage digest;
- normalized exact collection and marker snapshots;
- every node owner and resource class;
- every stage configured argv, cwd, environment policy, deadline, dependency,
  execution kind, and expected-node digest;
- all `2,817` exact `(node_id, owner, outcome)` records;
- unexpected deselection;
- qualification status/harness/scenario sets;
- Web UI required stages and outcomes;
- stage status/outcome sequence; and
- authoritative/admission/live/terminal flags.

Result:

- normalized projection digest:
  `sha256:6bab76e617a1225f01b26446bc825732591bc913fab50cae5f1ae529f6a58dfa`
- fixed-four versus forced-serial differences in retained fields:
  `0`

The two source identity digests intentionally differ because Task 8.8 evidence
was recorded in the OpenSpec task document between invocations. That
operator-evidence-only edit did not change collection: exact node sets,
owners, outcomes, stage contracts, qualification, and frontend results remain
identical.

## Rollback and independent admission

Direct legacy comparison:

```bash
./scripts/check-mainline-legacy.sh
```

It never represents current authority. A confirmed optimized authority
regression can be rolled back only by explicitly changing the canonical
wrapper implementation; candidate or regressed receipts are not reinterpreted
as legacy success.

Full clean architecture admission remains the independent command documented
in `architecture-admission-independence-evidence.md`. No architecture
admission, AOX launch, live provider, HPC, Chrome, MICU, or scientific
campaign was started during this cutover.
