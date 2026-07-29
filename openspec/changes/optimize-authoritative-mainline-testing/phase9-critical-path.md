# Phase 9 Post-Dedup/Post-Parallel Critical Path

Date: 2026-07-29

This report is repository/operator evidence only. It grants no merge,
architecture-admission, AOX, live-campaign, or scientific authority.

## Inputs

- pre-slice optimized sample:
  `/tmp/openzyme-optimized-sample-smoke-r1`
- post-slice shadow plan and exact general execution:
  `/tmp/openzyme-expanded-plan-workers3-r1`
- complete fixed-worker samples:
  `/tmp/openzyme-optimized-expanded-workers2-warm3-r1`,
  `/tmp/openzyme-optimized-expanded-warm1-r1`, and
  `/tmp/openzyme-optimized-expanded-workers4-warm2-r1`
- same-plan forced-serial sample:
  `/tmp/openzyme-optimized-expanded-forced-serial-warm4-r1`
- reverse and fixed-seed shuffled parallel observations:
  `/tmp/openzyme-parallel-reverse-ht71dupy` and
  `/tmp/openzyme-parallel-shuffle-5hwumm3e`
- post-slice plan digest:
  `sha256:845a664eb51ff272aac4b3fae887deb9aa5dcf4f5d3cbbdd2648a459bc8287c8`
- resource manifest digest:
  `sha256:41d8dc2efea009b1b0158191acfdb580e06fe2d5ccd19f3979a607cabb19d916`
- initial diagnostic worker policy: `3`; selected policy after comparison: `4`;
  hard maximum `4`, `--dist=loadfile`

The pre-slice and post-slice runs have different source identities because this
slice changes fresh SQLite initialization and expands the exact resource
manifest. Their comparison diagnoses the accepted optimization; it is not the
same-source five-pair performance acceptance required for authority cutover.

## Measured structural change

| Measure | Before | After |
| --- | ---: | ---: |
| General nodes | 2,800 | 2,801 |
| Qualification-owned nodes | 97 | 97 |
| General residual nodes | 2,703 | 2,704 |
| Resource-audited parallel nodes | 414 | 1,292 |
| Conservative serial nodes | 2,289 | 1,412 |
| Parallel partition wall time | 164.56 s | 95.70 s |
| Serial partition wall time | 278.82 s | 86.91 s |
| Merged general wall time | 443.30 s | 185.33 s |

The post-slice partition sum is `182.61 s`; exact collection, transition, merge,
and publication add `2.72 s`. The merged general stage is therefore 58.2%
shorter than the earlier candidate while executing one additional test.

The three worker loads were:

| Worker | Executed nodes | Cumulative node time |
| --- | ---: | ---: |
| `gw0` | 477 | 64.37 s |
| `gw1` | 412 | 87.07 s |
| `gw2` | 403 | 64.32 s |

## Fixed worker selection

All four complete samples executed and collected 2,801 nodes, verified the
qualification sidecar and final receipt offline, passed both frontend commands,
and produced the same outcome projection digest
`sha256:ed07b47fc17e7d605f446647b4a75b79c68693d20b1d016e063fe5dd3b74bf6c`.

| Mode | Total | General | Eligible partition | Serial fallback | CPU active | CPU iowait | CPU PSI some | IO PSI some |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed 2 | 280.09 s | 204.75 s | 115.53 s | 85.61 s | 12.21% | 0.60% | 0.47% | 0.71% |
| fixed 3 | 260.59 s | 184.82 s | 95.90 s | 85.24 s | 13.12% | 0.60% | 0.50% | 0.68% |
| fixed 4 | **251.22 s** | **175.95 s** | **86.69 s** | 85.55 s | 13.74% | 0.65% | 0.49% | 0.81% |
| forced serial | 389.59 s | 314.47 s | 224.73 s | 86.16 s | 10.05% | 0.46% | 0.47% | 0.60% |

Four fixed workers are selected: they give the lowest measured stable critical
path under the hard maximum. The extra IO pressure versus three workers is
small and bounded; the worker count remains explicit and never derives from
host CPU count. Relative to the same-plan forced-serial sample, fixed four
reduces total wall time by 35.5% and the general stage by 44.0%.

## Schedule and side-effect stability

The fixed-four canonical complete run and repeated general-only run produced
the same sorted `(node_id, outcome)` projection. Two additional exact-manifest
diagnostics changed only collection/scheduling order for the 1,292
resource-audited nodes:

| Diagnostic | Order | Duration | Result |
| --- | --- | ---: | --- |
| reverse | all 165 test modules in reverse lexical order | 87.94 s | 1,292 identical outcomes; no worker failure |
| shuffled | deterministic seed `20260729` | 88.18 s | 1,292 identical outcomes; no worker failure |

The conservative 1,412-node fallback remains in canonical serial order; an
exploratory full-repository reverse run was intentionally not promoted into a
contract because unclassified serial tests have no order-independence proof.
Every fixed, reverse, shuffled, and forced-serial comparison retained the same
functional outcome set. The reverse/shuffled runs used checkout-external worker
roots, and the source identity before and after remained
`sha256:c93d414d03d5b623c3435217728b091297f65b2dcc33fb6e94a6e48bab565e71`;
there was no unexplained persistent repository side effect and no node required
demotion.

## Same-source legacy and forced-serial parity

The legacy entry remained byte-for-byte unchanged and authoritative during this
comparison. All evidence below binds source identity
`sha256:1bd2fd8aaf07935aea49fc3f10e641eeb315472a6797205192837bd67f2454cb`.

| Evidence | Path | Result |
| --- | --- | --- |
| unchanged legacy complete run | `/tmp/openzyme-same-source-legacy-phase6-r1` | pass, 421.09 s |
| forced-serial candidate | `/tmp/openzyme-same-source-forced-serial-phase6-r1` | pass and offline verified, 390.40 s |
| exact legacy general observation | `/tmp/openzyme-same-source-legacy-general-observation-r1.json` | 2,801/2,801 pass, 351.56 s |
| original two-argument qualification | `/tmp/openzyme-same-source-legacy-qualification-r1` | pass, 66.59 s |

The forced-serial receipt collected and executed the same 2,801 distinct nodes
as the legacy general observation. Both sorted `(node_id, outcome)` projections
have digest
`sha256:ea8209c0ac7abbf2426f3518cc72eee57c4e283ea2a8636d38b548ebbdc62b94`;
all outcomes are `pass`. The candidate qualification sidecar verified the same
84 harness and 13 selected scenario nodes, and both required frontend stages
passed. The original two-argument qualification took 66.59 s versus 66.44 s
inside the candidate, a -0.15 s noise-level delta. Total forced-serial wall
time was 30.70 s (7.3%) below legacy while preserving exact obligations.

## Accepted migration/schema slice

The dominant repeated initialization cost came from fresh file-backed
`SQLiteRepositoryProvider` construction. A three-run microbenchmark measured
about `1.79 s` per fresh database while current-schema validation was about
`0.006 s`. The empty-database path had executed 36 migration scripts as
separate durable commits.

Fresh initialization now executes all current migrations plus
`PRAGMA user_version` in one `BEGIN IMMEDIATE` transaction. It retains the
existing current-schema verification and old-version upgrade paths. Injecting
invalid SQL in migration 18 proves that a failure rolls back every schema
object, leaves `user_version = 0`, closes the transaction, and restores foreign
key enforcement. The post-change fresh-provider microbenchmark is
`0.140–0.150 s`.

The most migration-sensitive module,
`apps/openzyme-host-api/tests/test_aox_cutover_live.py`, fell from `52.46 s`
in the pre-slice general trace to `7.96 s` in the post-slice trace while all
130 nodes still passed.

## Remaining serial critical path

| Module | Nodes | Time | Classification | Decision |
| --- | ---: | ---: | --- | --- |
| `test_sandbox_runtime.py` | 75 | 24.77 s | real deadlines, subprocess/control-socket cleanup, approval admission concurrency | keep serial; timeout and exact thread retirement are the invariant |
| `test_aox_attempt_supervision.py` | 17 | 12.23 s | process cleanup and signal retirement | keep serial/process-signal |
| `test_execution.py` | 107 | 12.20 s | mixed execution adapters and fixed-path fault fixtures | keep serial until node-level resource proof exists |
| `test_aox_cutover_live.py` | 130 | 7.96 s | file SQLite, loopback service, bounded lifecycle | keep serial; `bounded_service` remains disabled |
| `test_podman_sandbox.py` | 7 | 5.28 s | socket/container lifecycle | keep serial/sandbox |
| `test_transport_fault_matrix.py` | 18 | 3.95 s | transport fault and process lifecycle | keep serial |
| `test_test_gate_pytest_plugin.py` | 5 | 3.32 s | nested pytest/process evidence | keep serial/process |
| `test_runtime_commands.py` | 12 | 1.72 s | file-SQLite contention and worker claims | keep serial/file-SQLite |
| `test_mutation_quiescence.py` | 11 | 1.57 s | file-SQLite concurrency/barriers | keep serial/file-SQLite |

The remaining real waits are no longer the authority target's dominant cost.
Reducing contractual process timeouts, skipping cleanup, using blanket retry,
or promoting signal/sandbox tests would weaken evidence for only a few seconds
of possible gain, so those changes remain rejected.

## Benchmark-discovered legacy approval publication race

The first attempted final five-pair campaign stopped on optimized pair 1 warm;
a second campaign stopped on pair 4 cold. Both failures were the same S12
legacy-result test, first before the initial operation completed and then after
the second approval was resolved while the sandbox thread remained alive. The
test used the unchanged 10-second sandbox command deadline. Merely aligning an
earlier five-second observation loop with that deadline did not fix the second
failure and was not accepted as closure.

A deterministic two-connection regression inserted a barrier immediately
after `ApprovalRequestRepository.save(PENDING)`. Before correction, the
observer read the pending approval while no matching continuation existed.
Resolving in that interval committed the approval but
`resolve_for_approval()` had no continuation to advance, leaving the control
worker permanently in `WAITING_APPROVAL`.

The correction publishes the legacy operation, pending approval, approval
binding, and continuation in one short managed `BEGIN IMMEDIATE` transaction.
The wait and Host adapter execution begin only after commit, so no SQLite write
lock crosses external wall time. The deterministic regression changed from red
to green; the original S12 test passed 20 independent processes; and the full
75-node sandbox-runtime module passed. No command timeout, approval deadline,
cleanup assertion, retry policy, or owner fallback changed.

## Hotspot decisions after remeasurement

- **Polling and real waits:** no remaining fixed sleep is both dominant and
  semantically replaceable. The final campaign did expose a real partial-
  publication race rather than a slow wait; it was removed by atomic admission,
  not by changing any deadline. Sandbox/runtime and supervision waits still
  prove real deadlines, process-group retirement, control-socket closure, and
  signal handling. They remain serial with their original bounds; no fake
  clock, shortened/extended contractual timeout, or blanket retry was accepted.
- **App construction:** the measured repeated cost was fresh SQLite migration,
  not immutable FastAPI construction input. Reusing an app, dependency
  overrides, repository, connection, event loop, worker, or mutable root would
  cross test boundaries, so no app template/cache was introduced.
- **Migration/schema:** a digest-verified pristine database copy was considered
  but rejected. It would add template build/version identity and copy semantics
  while hiding the real empty-database migration path. Executing the existing
  migration bytes atomically reduced fresh startup to `0.140–0.150 s` and still
  exercises current-version verification and fail-fast rollback on every fresh
  database.
- **Fixture bytes and cleanup:** no immutable serialization or cleanup wait
  remains large enough to justify another sharing seam. Process, socket,
  sandbox, and file roots remain test-exclusive; all join/retirement assertions
  stay intact.

The accepted performance hotspot slice is atomic fresh SQLite initialization.
It has a focused rollback regression, updates the main architecture and V3
control-plane documents, passes the same-source legacy/forced-serial outcome
comparison, and is included in the fixed-worker, reverse, and shuffled results
above. The benchmark-discovered legacy admission correction is separately a
correctness/reliability prerequisite: it removes an externally observable
partial state without claiming speedup. The post-correction source must receive
a fresh five-pair campaign; every earlier sample remains diagnostic only.

## Final same-source five-pair acceptance

The post-correction campaign used one source identity
`sha256:235fde197e3c98cdec64c68251794ea65db55e67ec111b534357781026ea47f9`,
one host/toolchain identity, five process-cold samples, and each cold sample's
immediate warm partner. All 20 legacy/candidate invocations passed on their
first execution. There were no invalid, retried, drifted, or discarded
performance samples.

Raw evidence:

- legacy pairs: `/tmp/openzyme-final-v3-pair-{1..5}-legacy-{cold,warm}`
- optimized pairs:
  `/tmp/openzyme-final-v3-pair-{1..5}-optimized-{cold,warm}`
- legacy summary:
  `/tmp/openzyme-final-v3-legacy-summary/legacy-baseline-summary.json`
  (`sha256:8d5bf9626cc519e75c3645071473e6f335b85e59ee10398431d392fb2c3b6f11`)
- optimized comparison:
  `/tmp/openzyme-final-v3-optimized-summary/optimized-summary.json`
  (`sha256:2ea295a95311f63ca7fbee5905e48ddb0c513a2e7d19f0cfe7af9105a959426e`)

| Sample class | Legacy median | Legacy MAD / min / max | Optimized median | Optimized MAD / min / max | Reduction |
| --- | ---: | ---: | ---: | ---: | ---: |
| cold | 424.62 s | 1.24 / 422.63 / 425.89 s | 255.04 s | 1.19 / 252.41 / 256.22 s | **39.94%** |
| warm | 424.14 s | 1.20 / 420.83 / 425.34 s | 253.77 s | 0.82 / 252.91 / 254.65 s | **40.17%** |

The candidate collected and executed 2,808/2,808 nodes in every sample, with
collection digest
`sha256:23a4f70818f8c294d167f464d508381127cbe4a463bab0ba97dfeb718a8f9ede`
and outcome projection digest
`sha256:4b52c0c6a1f8cecab56455385c2fac7c067726a15f8256f4e2a7b9c3fae7b59a`.
Qualification was verified, both frontend commands passed, and every receipt
passed offline verification. Median planning/receipt overhead was 2.157%;
the maximum was 2.202%, below the 5% threshold.

Candidate stage medians were:

| Stage | Cold | Warm |
| --- | ---: | ---: |
| architecture qualification | 67.69 s | 66.94 s |
| general non-live pytest | 177.95 s | 177.51 s |
| compatibility audit | 3.47 s | 3.52 s |
| Web UI test | 0.214 s | 0.214 s |
| Web UI build | 0.114 s | 0.114 s |

The 4.23–4.27 minute candidate beats the proposal's 5–7 minute realistic
authoritative target. Its proven current lower envelope is about 4 minutes
13 seconds, not 10–60 seconds: qualification must run in its isolated process
and prove the exact sidecar; the 1,292-node xdist partition takes about
87 seconds; the conservative 1,419-node partition takes about 85–88 seconds;
and collection, compatibility, publication, and pure verification remain.
The two general partitions currently run in evidence-preserving order rather
than concurrently. Overlapping them or promoting more serial modules could
remove part of that sum only after new cross-partition resource/failure-order
proof; it is not an accepted bound in this change.

## Cutover closure

The three acceptance steps that were still open when this performance report
was first written are now complete:

1. On 2026-07-29 the user explicitly agreed to the immutable twenty-case replay
   corpus; the current-source 20/20 replay and same-source legacy/optimized
   parity are recorded in `replay-corpus-evidence.md`.
2. `scripts/check-mainline.sh` was atomically switched to the authority-only
   runner. The frozen sequential implementation remains
   `scripts/check-mainline-legacy.sh` and disclaims current authority at both
   entry and completion.
3. The post-cutover fixed-four authority and same-contract forced-serial
   commands both passed, each completed separate pure verification, and their
   2,817-node owner/outcome/frontend/qualification projections are equal after
   removing only invocation, source-recording, worker, output-path, and timing
   fields.

The raw paths, file digests, canonical digests, and normalized comparison are
recorded in `authority-cutover-evidence.md`. This historical performance report
does not itself grant current authority.
