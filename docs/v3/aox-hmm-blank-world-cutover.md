# AOX/HMM blank-world cutover evidence contract

Status: implementation and offline gates in progress; local Live cutover remains **NO-GO** until two real positive attempts and one real controlled fault attempt are sealed and verified on one commit/config identity.

This document describes the operator/evidence boundary implemented by `openzyme_host_api.aox_cutover_evidence`. It does not turn the historical S15 fixture into live evidence and does not authorize seeded state, cached scientific outputs, the reference notebook, or copied reference results as attempt inputs.

## Fixed scope

- Runtime remains single-process SQLite and the runner remains trusted-Host-only.
- Scientific failures are fail closed; an honest no-hit/no-candidate outcome may publish a healthy empty report but cannot claim discovery.
- The formal workflow uses `aox_motif_rule_score@1`, canonical real-sequence similarity, `cdhit_cluster_membership@1`, and digest-pinned workflow/image/SDK identities.
- The existing cumulative MICU ledger is read before and after every attempt. Its hard limit is exactly 100,000,000 input+output tokens; it is never reset by campaign setup.
- A bounded known-positive provider/HPC probe is separate from formal artifacts. Probe artifacts cannot enter formal operations or the published report.

## Formal AOX scientific closure

The formal NCBI request contains exactly 14 identities: the fixed 13 HMM-model
references plus coordinate reference `AAB57849.1`. The same sealed provider
aggregate is split by versioned calculations, not by copying historical files:

- `aox_hmm_reference_set_selection@1` produces the exact 13-record
  `AOX_ref21.fasta`, which alone enters MAFFT and hmmbuild;
- `aox_reference_selection@1` produces the single-record
  `AOX_coordinate_reference_AAB57849.1.fasta`;
- `aox_scoring_input_assembly@1` produces `AOX_scoring_input.fasta` as AAB first
  plus post-UniProt target records in lexical target-id order.

The discovery path is EBI HMMER `refprot` raw/parsed response →
`hmmer_score_filtered_accessions@1` with score strictly greater than `200` →
an exact conditional UniProt request → `aox_sequence_length_join@1` with
UniProt-derived sequence and inclusive length `650..700` → scoring input →
HMMalign/motif → conditional CD-HIT/similarity. HMMER length/sequence fields,
the probe, and the 13 model references cannot be substituted for UniProt target
truth.

The offline verifier derives one formal branch from sealed bytes:

| branch | stable empty reason | formal operations omitted |
|---|---|---|
| `hmmer_upstream_empty` | `no_hmmer_hits` or `no_filtered_hmmer_accessions` | UniProt, HMMalign, CD-HIT |
| `length_filter_empty` | `no_candidates_after_length_filter` | HMMalign, CD-HIT |
| `motif_filter_empty` | `no_candidates_after_motif_filter` | CD-HIT |
| `nonempty` | n/a | none of the reached chain |

For upstream empty, `provider_upstream_empty_receipt@1` binds the HMMER
score-filter artifact and derivation operation and proves
`provider_io_performed=false`; it has no fabricated invocation, operation,
request, or response digest. For either empty-target branch, HMMalign is not
fabricated: `aox_reference_only_scoring_alignment@1` materializes the verified
AAB-only scoring input. The exact reached/omitted operation set must agree with
the derived branch, and the isolated probe covers required capabilities omitted
from the formal graph.

## Clean-root preflight

Every attempt creates a new attempt root containing initially empty, distinct locations for:

- control-plane SQLite;
- artifact and blob storage;
- persistent executor sandboxes;
- an HPC workspace label/root;
- append-only evidence.

The public root proof contains only stable names, counts, identities and cache policy, never Host paths. `provider_cache_mode=bypass`, `evidence_cache_reuse=false` and `sqlite_preexisting=false` are mandatory. Existing attempt roots, symlinks, preloaded scientific files and unknown prerequisite fields are rejected.

Allowed prerequisite fields are closed to code/config identity only: commit, config/workflow/image/SDK digests, toolchain image digests, credential slot names, NCBI identity and prompt accessions. Credentials themselves and scientific bytes are forbidden.

Operator preflight example:

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover preflight \
  --campaign-root /tmp/openzyme-aox-cutover/<campaign-id> \
  --attempt-kind positive \
  --allowed-prerequisites /tmp/aox-allowed-prerequisites.json
```

`local_paths` in this command's stdout are operator-only launch inputs. They must not be copied into workspace/events/report/evidence projections.

## Attempt bundle

`aox_blank_world_attempt_bundle@1` is canonical sorted-key UTF-8 JSON wrapped by its SHA-256 payload digest. The payload binds:

- git commit, config, workflow selection, scoring contract/implementation, image and SDK;
- self-consistent clean-root proof and Host launch receipt;
- one continuous MICU ledger before/after transition;
- provider and toolchain invocation/job/operation receipts with sealed formal artifact ids;
- bounded known-positive probe receipts and probe-only artifacts;
- canonical session/message/task/approval/operation identities;
- artifact bytes, provenance and operation input/output digests;
- published report content artifact, source refs, claim links and final master response;
- scoring and similarity recomputation inputs/outputs;
- warnings, enrichment degradations and honest scientific outcome.

An eligible positive attempt additionally requires:

- cache-bypassed PubMed, exact-14 NCBI, and EBI HMMER `refprot` receipts, plus
  either a reached valid UniProt receipt or the strict upstream-empty skip
  receipt;
- completed MAFFT and hmmbuild receipts, plus reached HMMalign/CD-HIT receipts
  or a byte-derived branch that requires their formal omission;
- exactly one durable researcher, executor and reporter task, each explicitly completed;
- at least one approved controlled operation with the same operation identity;
- one canonical entry message, root-bound Host launch receipt, workspace/event digests, a non-empty final response and a published report;
- ledger-observed MICU attempt/token growth;
- a passed isolated known-positive provider/HPC attestation whose capability
  union with the reached formal branch is complete.

Failure evidence is still sealed when possible, but `cutover_eligible=false` and therefore stops the campaign before a second positive or GO decision.

## Known-positive probe contract and live gate

The product collector and offline verifier now declare
`aox_known_positive_probe@2` with
`probe_id="independent_globin_provider_hpc_probe"`. This is an implemented
attestation contract, not proof that a real `@2` campaign attempt has passed.
An AAB-only/MAFFT-only `@1` receipt is insufficient and rejected.

The bounded `@2` probe uses NCBI `NP_000509.1` and `NP_000549.1`, UniProt
`P68871` and `P69905`, and exactly six controlled operations: NCBI fetch,
UniProt fetch, MAFFT, hmmbuild, CD-HIT in protein mode at identity `1.0`, and
one HMMalign consuming the real HMM plus the real clustered UniProt FASTA. It
uses one isolated task/workspace/sandbox/source snapshot and binds raw HTTP
response-body digests rather than a parsed-FASTA digest presented as a provider
response digest. EBI HMMER is not duplicated in the probe because every formal
branch already reaches it.

Probe task, operation, invocation and artifact identities must be disjoint from
the formal path. Probe artifacts cannot be selected as formal inputs or cited
by the formal report. Until a real attempt emits this implemented schema and
passes the current offline verifier, the probe criterion remains NO-GO.

## Offline verifier

The verifier makes no network request. It rejects non-canonical/duplicate-key/non-finite JSON, malformed schemas, envelope extras, secret/private path projection, symlink traversal and unreadable artifacts without echoing Host paths. It recomputes:

- bundle, record, artifact content and provenance digests;
- operation/artifact and approval/operation lineage;
- report content/formal scope/claim artifact references;
- exact `aox_motif_rule_score@1` CSV from the sealed alignment;
- similarity nodes/edges/manifest from sealed candidates and CD-HIT membership;
- controlled one-bit fault proof and its source/terminal failure operations.

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover verify \
  --bundle <attempt-evidence-root>/attempt-bundle.json \
  --artifact-root <attempt-artifact-root>
```

Exit code is `0` only for a structurally and scientifically verified attempt; verification failure returns `2` and stable issue identities.

## Controlled fault attempt

The required fault contract is `sealed_provider_artifact_byte_flip@1`. A qualifying fault attempt must actually flip one bit in a sealed required-provider artifact and record:

- target artifact and relative path;
- byte offset;
- before/after content digests;
- source operation that emitted the before digest;
- the terminal `failed`/`recovery_failed` validation operation that observed the after digest;
- exact `artifact_content_digest_mismatch` failure code;
- a non-eligible failure report/outcome.

The offline verifier reverses the recorded bit to recompute the before digest and verifies both operation references. Setting `expected_failure_observed=true` without the bytes and failed operation is not evidence.

## Campaign reducer and GO rule

`aox_blank_world_campaign_decision@1` accepts exactly this order:

1. eligible positive attempt;
2. independent eligible positive attempt;
3. controlled fail-closed attempt.

All three pin the same commit/config/workflow/scoring/image/SDK identity and one continuous MICU ledger. Positive attempts must use distinct root/HPC labels, session/message/final-response identities and disjoint task, controlled-operation, provider invocation and toolchain job receipts. Scientific content digests may be identical when providers return the same bytes; execution receipts may not be reused.

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover decide \
  --attempt <positive-1-bundle> <positive-1-artifacts> \
  --attempt <positive-2-bundle> <positive-2-artifacts> \
  --attempt <fault-bundle> <fault-artifacts> \
  --output <campaign-root>/campaign-decision.json
```

Attempt bundles, driver-failure evidence and the decision use atomic no-replace writes plus file/directory fsync. A campaign driver exception produces append-only safe failure evidence and a precise NO-GO; it never falls through to GO.

Real campaign entry point:

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover run-live \
  --campaign-root /tmp/openzyme-aox-cutover/<campaign-id> \
  --identity /tmp/aox-campaign-identity.json \
  --allowed-prerequisites /tmp/aox-allowed-prerequisites.json \
  --approval-mode auto
```

Use `--approval-mode manual` for the Chrome-observed positive attempt. The
command runs positive 1, positive 2 and the controlled fault in order; any
missing receipt, failed offline verification, identity mismatch or MICU ledger
violation produces NO-GO and exit code `2`.

## Current acceptance boundary

Offline unit/eval success proves implementation behavior only. Local Live cutover becomes GO only after the real public product path also demonstrates:

- two clean-root positive runs with published reports and passed offline verification;
- one reached controlled provider-artifact fault with no eligible report/success;
- at least one Chrome-observed approval resume of the same operation plus consistent workspace/events/report/evidence and a clean console;
- focused, frontend, non-live, mainline, eval and live provider/LLM/HPC gates;
- a sealed decision from the real attempt digests and final cumulative MICU usage.

Until those artifacts exist, documentation and UI must state NO-GO. Historical S15 and deterministic fixtures remain `fixture_non_cutover` regardless of local test status.
