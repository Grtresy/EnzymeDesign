# Immutable Replay Corpus Parity Evidence

Date: 2026-07-29

Status: technical parity is closed. On 2026-07-29 the user explicitly agreed:
`同意使用这 20-case immutable replay corpus`. This agreement accepts the
immutable corpus below as the allowed equivalent of twenty disposable clean
revisions for Tasks 8.1–8.2 and the authority-cutover prerequisite. The corpus
itself remains non-authoritative and grants no merge, architecture-admission,
AOX, live-campaign, or scientific-evidence authority.

All paths below are checkout-external repository/operator evidence. None of the
artifacts can satisfy architecture admission, AOX launch, live-campaign, or
scientific-evidence contracts.

## Closed corpus identity

- corpus:
  `scripts/test-replay-corpus.json`
- corpus id:
  `openzyme_mainline_equivalent_replay_20260729`
- schema:
  `openzyme_test_replay_corpus@1`
- case count / distinct proof-node count:
  `20 / 20`
- corpus digest:
  `sha256:136cacea60eb8022fbe58672c0c4801545a381cb00343c455c7a2406f898d202`

The loader rejects count/order drift, duplicate or missing proof nodes, an open
green projection, an unknown expected projection, digest drift, and proof nodes
that are absent from the current complete non-live collection.

## Same-source legacy/optimized projection

The comparison binds source identity
`sha256:1bd2fd8aaf07935aea49fc3f10e641eeb315472a6797205192837bd67f2454cb`.

| Evidence | Path | Digest / result |
| --- | --- | --- |
| legacy exact general execution | `/tmp/openzyme-same-source-legacy-general-observation-r1.json` | `sha256:4ed728173360f8823f6ddd6b3b550564aecbe8561927d7bcbd19868b610f165a`; `2,801/2,801`, exit `0` |
| optimized same-plan forced serial | `/tmp/openzyme-same-source-forced-serial-phase6-r1/mainline-candidate-receipt.json` | `sha256:86ffeaa3725c3fa32171353d806bcc08a9a1bcf2eccaa3f29fad56d3923ba6c6`; pass and offline verified |
| complete sorted outcome projection | both artifacts | `sha256:ea8209c0ac7abbf2426f3518cc72eee57c4e283ea2a8636d38b548ebbdc62b94`; zero mismatches |

Selecting the corpus's twenty exact proof nodes from both raw result sets gives
`20` present in legacy, `20` present in optimized, no missing node, and no
outcome mismatch. Every proof node passes in both paths. A passing proof node
for a negative case means that the test observed and asserted the case's
specified fail-closed projection; it does not reinterpret the injected failure
as a green product result.

| Case | Boundary | Expected transformation | Legacy proof | Optimized proof |
| --- | --- | --- | --- | --- |
| `01-green-complete` | complete gate | pass | pass | pass |
| `02-green-legacy-obligations` | legacy contract | pass | pass | pass |
| `03-missing-owner` | shadow ownership | fail at planning | pass | pass |
| `04-duplicate-owner` | plan ownership | fail at planning | pass | pass |
| `05-forbidden-marker` | non-live policy | fail at planning | pass | pass |
| `06-source-config-environment-drift` | source contract | fail at planning | pass | pass |
| `07-qualification-node-missing-from-general` | qualification ownership | fail at planning | pass | pass |
| `08-qualification-failure` | qualification | fail before general | pass | pass |
| `09-qualification-timeout` | qualification | fail before general | pass | pass |
| `10-general-timeout` | general pytest | fail before frontend | pass | pass |
| `11-missing-stage-evidence` | receipt stage closure | fail verification | pass | pass |
| `12-malformed-or-duplicate-result` | receipt integrity | fail verification | pass | pass |
| `13-unexpected-deselection` | exact general selection | fail verification | pass | pass |
| `14-missing-frontend-result` | frontend closure | fail verification | pass | pass |
| `15-prior-invocation-evidence` | invocation binding | fail verification | pass | pass |
| `16-worker-crash` | parallel worker | fail general stage | pass | pass |
| `17-leaked-process` | parallel worker | fail general stage | pass | pass |
| `18-stale-resource-proof` | resource manifest | fail at planning | pass | pass |
| `19-forbidden-shared-resource` | resource isolation | fail at planning | pass | pass |
| `20-product-live-boundary` | authority consumer | consumer rejects receipt | pass | pass |

## Authority-preparation source replay

The corpus was re-collected and executed from the final pre-cutover source
after adding the isolated shadow/authority verifier domains, frozen rollback
wrapper, and authority CLI contract:

- evidence root:
  `/tmp/openzyme-final-replay-v5-precutover-r1`
- replay source identity:
  `sha256:3429c35e2c6cc2b183528bfc6d9ddaab5131c8a12b2d13384eae3d3db89231f5`
- plan digest:
  `sha256:83fdc64521bcfd3e897002813a8d5489ae8c52a1fefbdde8984f27d883d774d4`
- receipt digest:
  `sha256:322b80bc8befe44cd9e8e9b8a4d644ebf933cdf039213f7aadf77451f02cff61`
- result:
  `20/20` exact proof nodes passed; separate pure verification passed
- immutable flags:
  `authoritative=false`, `admission_eligible=false`, `live_eligible=false`

This replay proves that the pinned transformations still close after
authority-mode preparation. Later documentation-only evidence recording is not
silently folded into that source digest, and the replay remains a
`focused_diagnostic` receipt.
Tasks 8.1–8.2 are closed by the immutable corpus, the same-source parity
projection, the current-source replay above, and the explicit agreement quoted
at the top of this document. No mismatch remains in the required node-set,
outcome, stage, frontend, qualification, environment, or terminal projections.
